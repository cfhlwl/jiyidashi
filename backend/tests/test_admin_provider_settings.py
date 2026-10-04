from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.admin_models import (
    AdminAccount,
    AdminAuditEvent,
    AdminRole,
    ProviderConfiguration,
    ProviderRuntimeEvidence,
    ProviderService,
)
from app.auth_models import AuthRateLimitBucket
from app.core.config import Settings
from app.core.db import SessionLocal
from app.embedding_policy import (
    MEMORY_EMBEDDING_MAX_INPUT_CHARS,
    MEMORY_EMBEDDING_MODEL,
)
from app.admin_schemas import AdminProviderConfigWrite
from app.services.admin_provider_service import (
    _runtime_state,
    update_provider_configuration,
)
from app.services.admin_security import AdminOperationError, hash_admin_password
from app.services.provider_config_service import (
    ProviderRuntimeConfigError,
    get_runtime_provider_settings,
    invalidate_provider_runtime_cache,
    provider_runtime_fingerprint,
    validate_provider_policy,
)


def _reset_admin_login_buckets() -> None:
    with SessionLocal() as db:
        db.execute(
            delete(AuthRateLimitBucket).where(
                AuthRateLimitBucket.scope.in_(
                    ("admin_login_ip", "admin_login_account_ip")
                )
            )
        )
        db.commit()


def _create_admin(role: AdminRole) -> tuple[str, str]:
    _reset_admin_login_buckets()
    email = f"provider-admin-{uuid4()}@example.com"
    password = "Provider-Admin-Test-123!"
    with SessionLocal() as db:
        db.add(
            AdminAccount(
                email=email,
                display_name="Provider Admin",
                password_hash=hash_admin_password(password),
                role=role.value,
                disabled=False,
                revision=0,
            )
        )
        db.commit()
    return email, password


async def _login(client, role: AdminRole) -> dict[str, str]:
    email, password = _create_admin(role)
    response = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("jiyi_admin_csrf")
    assert csrf
    return {"X-CSRF-Token": csrf}


def _ai_payload(**overrides):
    payload = {
        "expected_revision": None,
        "enabled": True,
        "provider_type": "openai",
        "base_url": "https://api.openai.test/v1",
        "model": "gpt-test",
        "timeout_seconds": 20,
        "max_input_chars": 32000,
        "max_output_tokens": 2048,
        "min_confidence": None,
        "api_key": "sk-admin002-first-secret",
        "clear_api_key": False,
    }
    payload.update(overrides)
    return payload


async def test_provider_settings_are_readable_but_only_super_admin_can_mutate(client):
    for role in (AdminRole.OPERATOR, AdminRole.SUPPORT_READONLY):
        client.cookies.clear()
        headers = await _login(client, role)
        readable = await client.get("/admin/api/v1/settings/providers")
        assert readable.status_code == 200
        assert {item["service"] for item in readable.json()["services"]} == {
            "AI",
            "ASR",
            "EMBEDDING",
        }

        denied = await client.put(
            "/admin/api/v1/settings/providers/ai",
            headers=headers,
            json=_ai_payload(),
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "ADMIN_PERMISSION_DENIED"


async def test_provider_mutation_requires_csrf(client):
    client.cookies.clear()
    await _login(client, AdminRole.SUPER_ADMIN)
    denied = await client.put(
        "/admin/api/v1/settings/providers/ai",
        json=_ai_payload(),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "ADMIN_CSRF_REQUIRED"


async def test_secret_is_write_only_encrypted_preserved_rotated_and_explicitly_cleared(client):
    client.cookies.clear()
    headers = await _login(client, AdminRole.SUPER_ADMIN)

    created = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(),
    )
    assert created.status_code == 200, created.text
    first = created.json()
    assert first["configured"] is True
    assert first["revision"] == 0
    assert "api_key" not in first

    with SessionLocal() as db:
        row = db.get(ProviderConfiguration, ProviderService.AI.value)
        assert row is not None
        assert row.credential_override is True
        assert row.credential_ciphertext
        assert "sk-admin002-first-secret" not in row.credential_ciphertext
        first_ciphertext = row.credential_ciphertext
        audit = db.scalar(
            select(AdminAuditEvent)
            .where(AdminAuditEvent.action == "PROVIDER_CONFIG_UPDATE")
            .order_by(AdminAuditEvent.created_at.desc())
            .limit(1)
        )
        assert audit is not None
        assert audit.metadata_json["credential_changed"] is True
        assert "sk-admin002-first-secret" not in str(audit.metadata_json)

    safe_get = await client.get("/admin/api/v1/settings/providers")
    assert safe_get.status_code == 200
    assert "sk-admin002-first-secret" not in safe_get.text
    assert "credential_ciphertext" not in safe_get.text

    preserved = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(
            expected_revision=0,
            model="gpt-test-v2",
            api_key=None,
        ),
    )
    assert preserved.status_code == 200
    assert preserved.json()["revision"] == 1
    assert preserved.json()["configured"] is True
    with SessionLocal() as db:
        row = db.get(ProviderConfiguration, ProviderService.AI.value)
        assert row is not None
        assert row.credential_ciphertext == first_ciphertext

    rotated = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(
            expected_revision=1,
            model="gpt-test-v2",
            api_key="sk-admin002-rotated-secret",
        ),
    )
    assert rotated.status_code == 200
    assert rotated.json()["revision"] == 2
    with SessionLocal() as db:
        row = db.get(ProviderConfiguration, ProviderService.AI.value)
        assert row is not None
        assert row.credential_ciphertext != first_ciphertext
        assert "sk-admin002-rotated-secret" not in row.credential_ciphertext

    cleared = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(
            expected_revision=2,
            enabled=False,
            model="gpt-test-v2",
            api_key=None,
            clear_api_key=True,
        ),
    )
    assert cleared.status_code == 200
    assert cleared.json()["revision"] == 3
    assert cleared.json()["configured"] is False
    with SessionLocal() as db:
        row = db.get(ProviderConfiguration, ProviderService.AI.value)
        assert row is not None
        assert row.credential_override is True
        assert row.credential_ciphertext is None


async def test_preserved_db_secret_cannot_move_to_new_endpoint_origin(client):
    client.cookies.clear()
    headers = await _login(client, AdminRole.SUPER_ADMIN)

    created = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(),
    )
    assert created.status_code == 200

    redirected = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(
            expected_revision=0,
            base_url="https://attacker.example.test/v1",
            api_key=None,
        ),
    )
    assert redirected.status_code == 409
    assert (
        redirected.json()["detail"]
        == "ADMIN_PROVIDER_CREDENTIAL_DESTINATION_CHANGED"
    )

    rotated = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(
            expected_revision=0,
            base_url="https://attacker.example.test/v1",
            api_key="sk-explicit-replacement-secret",
        ),
    )
    assert rotated.status_code == 200
    assert rotated.json()["revision"] == 1


def test_bootstrap_secret_cannot_move_to_new_endpoint_origin_without_replacement():
    settings = Settings(
        app_env="test",
        ai_provider="openai",
        ai_base_url="https://api.openai.test/v1",
        ai_api_key="bootstrap-server-secret",
        ai_model="bootstrap-model",
        provider_config_master_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    with SessionLocal() as db:
        actor = AdminAccount(
            email=f"bootstrap-provider-{uuid4()}@example.com",
            display_name="Bootstrap Provider Admin",
            password_hash=hash_admin_password("Provider-Bootstrap-Test-123!"),
            role=AdminRole.SUPER_ADMIN.value,
            disabled=False,
            revision=0,
        )
        db.add(actor)
        db.flush()

        with pytest.raises(
            AdminOperationError,
            match="ADMIN_PROVIDER_CREDENTIAL_DESTINATION_CHANGED",
        ):
            update_provider_configuration(
                db,
                actor=actor,
                service=ProviderService.AI,
                payload=AdminProviderConfigWrite(
                    expected_revision=None,
                    enabled=True,
                    provider_type="openai",
                    base_url="https://attacker.example.test/v1",
                    model="bootstrap-model",
                    timeout_seconds=30,
                    max_input_chars=64000,
                    max_output_tokens=4096,
                    min_confidence=None,
                    api_key=None,
                    clear_api_key=False,
                ),
                settings=settings,
            )
        db.rollback()


async def test_provider_revision_conflict_fails_closed(client):
    client.cookies.clear()
    headers = await _login(client, AdminRole.SUPER_ADMIN)
    created = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(),
    )
    assert created.status_code == 200

    stale = await client.put(
        "/admin/api/v1/settings/providers/ai",
        headers=headers,
        json=_ai_payload(expected_revision=99, api_key=None),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "ADMIN_STATE_STALE"


def test_production_provider_url_must_be_https():
    settings = Settings(
        app_env="production",
        enable_dev_auth=False,
        jwt_secret="x" * 48,
        auth_email_delivery_mode="smtp",
        auth_smtp_host="smtp.example.com",
        auth_smtp_from="noreply@example.com",
        auth_public_base_url="https://jiyi.example.com",
    )
    with pytest.raises(
        ProviderRuntimeConfigError,
        match="PROVIDER_BASE_URL_HTTPS_REQUIRED",
    ):
        validate_provider_policy(
            service=ProviderService.AI,
            enabled=True,
            provider_type="openai",
            base_url="http://provider.example.com/v1",
            model="gpt-test",
            timeout_seconds=30,
            max_input_chars=1000,
            max_output_tokens=100,
            min_confidence=None,
            credential_configured=True,
            settings=settings,
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://secret@example.com/v1",
        "https://example.com/v1?api_key=secret",
        "https://example.com/v1#secret",
    ],
)
def test_provider_base_url_cannot_embed_credentials_or_secret_parameters(base_url: str):
    with pytest.raises(
        ProviderRuntimeConfigError,
        match="PROVIDER_BASE_URL_INVALID",
    ):
        validate_provider_policy(
            service=ProviderService.AI,
            enabled=False,
            provider_type="openai",
            base_url=base_url,
            model="gpt-test",
            timeout_seconds=30,
            max_input_chars=1000,
            max_output_tokens=100,
            min_confidence=None,
            credential_configured=False,
            settings=Settings(app_env="test"),
        )


def test_embedding_policy_cannot_change_model_or_input_limit():
    settings = Settings(app_env="test")
    with pytest.raises(
        ProviderRuntimeConfigError,
        match="EMBEDDING_MODEL_POLICY_LOCKED",
    ):
        validate_provider_policy(
            service=ProviderService.EMBEDDING,
            enabled=False,
            provider_type="openai",
            base_url="https://api.openai.test/v1",
            model="text-embedding-3-large",
            timeout_seconds=30,
            max_input_chars=MEMORY_EMBEDDING_MAX_INPUT_CHARS,
            max_output_tokens=None,
            min_confidence=None,
            credential_configured=False,
            settings=settings,
        )
    with pytest.raises(
        ProviderRuntimeConfigError,
        match="EMBEDDING_INPUT_POLICY_LOCKED",
    ):
        validate_provider_policy(
            service=ProviderService.EMBEDDING,
            enabled=False,
            provider_type="openai",
            base_url="https://api.openai.test/v1",
            model=MEMORY_EMBEDDING_MODEL,
            timeout_seconds=30,
            max_input_chars=MEMORY_EMBEDDING_MAX_INPUT_CHARS - 1,
            max_output_tokens=None,
            min_confidence=None,
            credential_configured=False,
            settings=settings,
        )



def test_provider_verification_requires_current_runtime_fingerprint():
    now = datetime.now(UTC)
    old_settings = Settings(
        app_env="test",
        ai_provider="openai",
        ai_base_url="https://api.openai.test/v1",
        ai_api_key="same-secret",
        ai_model="revision-a",
    )
    new_settings = old_settings.model_copy(update={"ai_model": "revision-b"})
    old_fingerprint = provider_runtime_fingerprint(old_settings, ProviderService.AI)
    new_fingerprint = provider_runtime_fingerprint(new_settings, ProviderService.AI)
    assert old_fingerprint != new_fingerprint

    with SessionLocal() as db:
        # Simulate a stale worker finishing revision A after revision B was already saved.
        db.add(
            ProviderRuntimeEvidence(
                service=ProviderService.AI.value,
                config_fingerprint=old_fingerprint,
                last_success_at=now,
                last_failure_at=None,
                updated_at=now,
            )
        )
        db.commit()

        assert (
            _runtime_state(
                db,
                service=ProviderService.AI,
                enabled=True,
                configured=True,
                runtime_fingerprint=old_fingerprint,
                now=now,
            )
            == "NORMAL"
        )
        assert (
            _runtime_state(
                db,
                service=ProviderService.AI,
                enabled=True,
                configured=True,
                runtime_fingerprint=new_fingerprint,
                now=now,
            )
            == "ENABLED_UNVERIFIED"
        )

        db.add(
            ProviderRuntimeEvidence(
                service=ProviderService.AI.value,
                config_fingerprint=new_fingerprint,
                last_success_at=now,
                last_failure_at=None,
                updated_at=now,
            )
        )
        db.commit()
        assert (
            _runtime_state(
                db,
                service=ProviderService.AI,
                enabled=True,
                configured=True,
                runtime_fingerprint=new_fingerprint,
                now=now,
            )
            == "NORMAL"
        )


def test_runtime_cache_converges_after_bounded_ttl(monkeypatch):
    import app.services.provider_config_service as provider_runtime

    clock = [100.0]
    base = Settings(
        app_env="test",
        ai_provider="openai",
        ai_api_key="bootstrap-secret",
        ai_model="bootstrap-model",
        provider_config_cache_ttl_seconds=1.0,
    )
    monkeypatch.setattr(provider_runtime, "monotonic", lambda: clock[0])
    monkeypatch.setattr(provider_runtime, "get_settings", lambda: base)
    invalidate_provider_runtime_cache()

    with SessionLocal() as db:
        db.add(
            ProviderConfiguration(
                service=ProviderService.AI.value,
                enabled=True,
                provider_type="openai",
                base_url="https://api.openai.test/v1",
                model="revision-a",
                timeout_seconds=20,
                max_input_chars=2000,
                max_output_tokens=200,
                min_confidence=None,
                credential_override=False,
                credential_ciphertext=None,
                revision=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()

    first = get_runtime_provider_settings()
    assert first.ai_model == "revision-a"

    with SessionLocal() as db:
        row = db.get(ProviderConfiguration, ProviderService.AI.value)
        assert row is not None
        row.model = "revision-b"
        row.revision = 1
        db.commit()

    clock[0] = 100.5
    assert get_runtime_provider_settings().ai_model == "revision-a"

    clock[0] = 101.1
    assert get_runtime_provider_settings().ai_model == "revision-b"


def test_same_process_invalidation_fences_inflight_cache_reload(monkeypatch):
    import app.services.provider_config_service as provider_runtime

    base = Settings(
        app_env="test",
        ai_provider="openai",
        ai_api_key="bootstrap-secret",
        ai_model="bootstrap-model",
        provider_config_cache_ttl_seconds=10.0,
    )
    stale = base.model_copy(update={"ai_model": "stale-model"})
    fresh = base.model_copy(update={"ai_model": "fresh-model"})
    calls: list[str] = []

    monkeypatch.setattr(provider_runtime, "get_settings", lambda: base)
    monkeypatch.setattr(provider_runtime, "monotonic", lambda: 100.0)

    def fake_reload(_db, *, settings):
        assert settings is base
        calls.append("reload")
        if len(calls) == 1:
            provider_runtime.invalidate_provider_runtime_cache()
            return stale
        return fresh

    monkeypatch.setattr(
        provider_runtime,
        "runtime_provider_settings_from_db",
        fake_reload,
    )
    provider_runtime.invalidate_provider_runtime_cache()

    resolved = provider_runtime.get_runtime_provider_settings()
    assert resolved.ai_model == "fresh-model"
    assert calls == ["reload", "reload"]

    # The fresh snapshot is now cached; the stale pre-invalidation read never won.
    assert provider_runtime.get_runtime_provider_settings().ai_model == "fresh-model"
    assert calls == ["reload", "reload"]
