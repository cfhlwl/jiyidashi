from __future__ import annotations

import asyncio
import inspect
import json
import logging
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError

import app.api.account_delete as account_delete_api
import app.api.data_delete as data_delete_api
import app.main as main_module
from app.core.config import Settings
from app.core.observability import emit_operational_event
from app.data_deletion_models import DataDeletionStatus
from app.deps import get_authenticated_user_id
from app.main import app
from app.services.account_deletion_service import (
    AccountDeletionError,
    AccountDeletionResult,
)
from app.services.ai_gateway import (
    AIGateway,
    AIGatewayError,
    AIImageInferenceRequest,
    AIInferenceRequest,
    AIProviderError,
    AIProviderResult,
)
from app.services.data_deletion_service import (
    DataDeletionError,
    DataDeletionResult,
)
from app.services.object_storage import (
    ObjectNotFound,
    ObjectStorageError,
    S3ObjectStorage,
    get_object_storage,
)

LOGGER = "jiyidashi.observability"


def _events(caplog) -> list[dict]:
    events = []
    for record in caplog.records:
        if record.name != LOGGER:
            continue
        events.append(json.loads(record.getMessage()))
    return events


def _event(caplog, name: str) -> dict:
    matching = [item for item in _events(caplog) if item["event"] == name]
    assert matching, f"missing observability event {name}: {_events(caplog)}"
    return matching[-1]


@pytest.mark.asyncio
async def test_request_id_generation_propagation_and_normalization(client, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    generated = await client.get("/health")
    assert generated.status_code == 200
    assert str(UUID(generated.headers["X-Request-ID"])) == generated.headers["X-Request-ID"]

    incoming = UUID("ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF")
    propagated = await client.get(
        "/health",
        headers={"X-Request-ID": str(incoming).upper()},
    )
    assert propagated.headers["X-Request-ID"] == str(incoming)

    malformed = await client.get(
        "/health",
        headers={"X-Request-ID": "free-form-request-id-is-not-allowed"},
    )
    replacement = malformed.headers["X-Request-ID"]
    assert str(UUID(replacement)) == replacement
    assert replacement != "free-form-request-id-is-not-allowed"


@pytest.mark.asyncio
async def test_http_event_uses_route_template_and_never_logs_sensitive_request_data(
    client,
    auth_headers,
    caplog,
):
    caplog.set_level(logging.INFO, logger=LOGGER)
    caplog.clear()

    title = "MEMORY_TITLE_SENTINEL_6d8265"
    content = "MEMORY_CONTENT_SENTINEL_d88c1a"
    latitude = 37.123456789
    longitude = -121.987654321
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "title": title,
            "content": content,
            "latitude": latitude,
            "longitude": longitude,
        },
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    query_secret = "QUERY_SENTINEL_42f91f"
    caplog.clear()
    response = await client.get(
        f"/v1/memories/{memory_id}?probe={query_secret}",
        headers=auth_headers,
    )
    assert response.status_code == 200

    event = _event(caplog, "http.request.completed")
    assert event["route"] == "/v1/memories/{memory_id}"
    assert event["method"] == "GET"
    assert event["status_code"] == 200
    assert UUID(event["request_id"])

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in (
        memory_id,
        query_secret,
        title,
        content,
        str(latitude),
        str(longitude),
        auth_headers["Authorization"],
        "Authorization",
        "Cookie",
    ):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_health_liveness_unchanged_and_readiness_fails_closed(client, monkeypatch):
    live = await client.get("/health")
    assert live.status_code == 200
    assert live.json() == {"status": "ok", "service": "jiyidashi-backend"}

    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ready"}

    class BrokenEngine:
        def connect(self):
            raise RuntimeError(
                "postgresql://user:DB_SECRET_SENTINEL@db.internal:5432/private"
            )

    monkeypatch.setattr(main_module, "engine", BrokenEngine())
    failed = await client.get("/health/ready")
    assert failed.status_code == 503
    assert failed.json() == {"status": "not_ready", "database": "unavailable"}
    body = failed.text
    assert "DB_SECRET_SENTINEL" not in body
    assert "db.internal" not in body


def test_observability_event_surface_is_explicit_and_fail_safe(monkeypatch, caplog):
    signature = inspect.signature(emit_operational_event)
    assert all(
        parameter.kind != inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    for forbidden in (
        "user_id",
        "memory_id",
        "media_id",
        "content",
        "latitude",
        "longitude",
        "object_key",
        "url",
        "authorization",
        "email",
    ):
        assert forbidden not in signature.parameters

    logger = logging.getLogger(LOGGER)

    def fail_log(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("logging backend failed")

    monkeypatch.setattr(logger, "info", fail_log)
    emit_operational_event(event="telemetry.failure.must.not.escape")


class _TelemetryProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        assert "PROMPT_SECRET_SENTINEL" in request.input_text
        return AIProviderResult(
            output_text="OUTPUT_SECRET_SENTINEL",
            provider="fixture-provider",
            model="fixture-model",
            provider_request_id="provider-safe-request",
            input_tokens=11,
            output_tokens=7,
        )

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        assert request.image_bytes == b"IMAGE_BYTES_SECRET_SENTINEL"
        return AIProviderResult(
            output_text="IMAGE_OUTPUT_SECRET_SENTINEL",
            provider="fixture-provider",
            model="fixture-image-model",
            provider_request_id="provider-image-safe-request",
            input_tokens=13,
            output_tokens=5,
        )


class _FailingProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AIProviderError("AI_PROVIDER_FAILED", retryable=True)

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        raise AIProviderError("AI_PROVIDER_FAILED", retryable=False)


class _CancelledProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise asyncio.CancelledError

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        raise asyncio.CancelledError


def _ai_settings() -> Settings:
    return Settings(
        app_env="test",
        ai_provider="disabled",
        ai_model="configured-model",
        ai_timeout_seconds=1,
    )


@pytest.mark.asyncio
async def test_ai_gateway_success_metrics_exclude_prompt_output_and_image_bytes(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    gateway = AIGateway(_ai_settings(), _TelemetryProvider())

    text_result = await gateway.infer(
        AIInferenceRequest(
            purpose="observability.text",
            system_instruction="SYSTEM_SECRET_SENTINEL",
            input_text="PROMPT_SECRET_SENTINEL",
        )
    )
    image_result = await gateway.infer_image(
        AIImageInferenceRequest(
            purpose="observability.image",
            system_instruction="IMAGE_SYSTEM_SECRET_SENTINEL",
            input_text="IMAGE_INPUT_SECRET_SENTINEL",
            image_bytes=b"IMAGE_BYTES_SECRET_SENTINEL",
            content_type="image/jpeg",
        )
    )

    events = [
        item for item in _events(caplog)
        if item["event"] == "ai.inference.completed"
    ]
    assert len(events) == 2
    assert events[0]["gateway_request_id"] == text_result.provenance.gateway_request_id
    assert events[0]["purpose"] == "observability.text"
    assert events[0]["provider"] == "fixture-provider"
    assert events[0]["model"] == "fixture-model"
    assert events[0]["provider_request_id"] == "provider-safe-request"
    assert events[0]["input_tokens"] == 11
    assert events[0]["output_tokens"] == 7
    assert events[1]["gateway_request_id"] == image_result.provenance.gateway_request_id

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in (
        "SYSTEM_SECRET_SENTINEL",
        "PROMPT_SECRET_SENTINEL",
        "OUTPUT_SECRET_SENTINEL",
        "IMAGE_SYSTEM_SECRET_SENTINEL",
        "IMAGE_INPUT_SECRET_SENTINEL",
        "IMAGE_BYTES_SECRET_SENTINEL",
        "IMAGE_OUTPUT_SECRET_SENTINEL",
    ):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_ai_gateway_failure_metrics_and_cancellation_semantics(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    failing = AIGateway(_ai_settings(), _FailingProvider())

    with pytest.raises(AIGatewayError):
        await failing.infer(
            AIInferenceRequest(
                purpose="observability.failure",
                system_instruction="secret-system",
                input_text="secret-input",
            )
        )
    event = _event(caplog, "ai.inference.failed")
    assert event["error_code"] == "AI_PROVIDER_FAILED"
    assert event["retryable"] is True
    assert event["purpose"] == "observability.failure"
    assert UUID(event["gateway_request_id"])

    cancelled = AIGateway(_ai_settings(), _CancelledProvider())
    with pytest.raises(asyncio.CancelledError):
        await cancelled.infer(
            AIInferenceRequest(
                purpose="observability.cancelled",
                system_instruction="system",
                input_text="input",
            )
        )


class _FailingStorageClient:
    def generate_presigned_url(self, **kwargs):
        del kwargs
        raise RuntimeError(
            "https://storage.secret.test/OBJECT_KEY_SECRET?signature=URL_SECRET"
        )


class _NotFoundStorageClient:
    def head_object(self, **kwargs):
        del kwargs
        raise ClientError(
            {
                "Error": {"Code": "NoSuchKey", "Message": "OBJECT_KEY_SECRET"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            },
            "HeadObject",
        )


def _storage_with(client) -> S3ObjectStorage:
    storage = object.__new__(S3ObjectStorage)
    storage._settings = Settings(
        app_env="test",
        storage_backend="s3",
        storage_bucket="BUCKET_SECRET_SENTINEL",
        storage_access_key_id="ACCESS_SECRET_SENTINEL",
        storage_secret_access_key="KEY_SECRET_SENTINEL",
        storage_endpoint_url="https://storage.secret.test",
    )
    storage._client = client
    return storage


def test_storage_failure_event_is_safe_and_not_found_is_not_noisy(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    storage = _storage_with(_FailingStorageClient())

    with pytest.raises(ObjectStorageError):
        storage.sign_upload(
            "OBJECT_KEY_SECRET_SENTINEL",
            "image/jpeg",
        )
    event = _event(caplog, "storage.operation.failed")
    assert event["operation"] == "sign_upload"
    assert event["error_code"] == "STORAGE_SIGN_UPLOAD_FAILED"

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in (
        "OBJECT_KEY_SECRET_SENTINEL",
        "BUCKET_SECRET_SENTINEL",
        "ACCESS_SECRET_SENTINEL",
        "KEY_SECRET_SENTINEL",
        "storage.secret.test",
        "URL_SECRET",
    ):
        assert forbidden not in rendered

    caplog.clear()
    not_found = _storage_with(_NotFoundStorageClient())
    with pytest.raises(ObjectNotFound):
        not_found.stat_object("OBJECT_KEY_SECRET_SENTINEL")
    assert not [
        item for item in _events(caplog)
        if item["event"] == "storage.operation.failed"
    ]


@pytest.fixture
def deletion_api_overrides():
    user_id = uuid4()
    app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
    app.dependency_overrides[get_object_storage] = lambda: object()
    yield user_id
    app.dependency_overrides.pop(get_authenticated_user_id, None)
    app.dependency_overrides.pop(get_object_storage, None)


@pytest.mark.asyncio
async def test_data_delete_progress_and_failure_telemetry(
    client,
    monkeypatch,
    caplog,
    deletion_api_overrides,
):
    del deletion_api_overrides
    caplog.set_level(logging.INFO, logger=LOGGER)
    request_id = uuid4()

    monkeypatch.setattr(data_delete_api, "lock_external_data_delete_entry", lambda *a, **k: None)
    monkeypatch.setattr(
        data_delete_api,
        "delete_all_user_data",
        lambda *a, **k: DataDeletionResult(
            request_id=request_id,
            status=DataDeletionStatus.WAITING_STORAGE_QUIET,
            completed=False,
            retry_after_seconds=5,
            deleted_counts={"PRIVATE_RESOURCE_SENTINEL": 99},
        ),
    )
    response = await client.post(
        "/v1/data/delete",
        json={
            "request_id": str(request_id),
            "confirmation": "DELETE_MY_DATA",
        },
    )
    assert response.status_code == 202
    progress = _event(caplog, "data_deletion.progress")
    assert progress["operation_request_id"] == str(request_id)
    assert progress["operation_status"] == DataDeletionStatus.WAITING_STORAGE_QUIET.value
    assert progress["completed"] is False

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "PRIVATE_RESOURCE_SENTINEL" not in rendered
    assert "DELETE_MY_DATA" not in rendered

    caplog.clear()

    def fail(*args, **kwargs):
        del args, kwargs
        raise DataDeletionError("DATA_DELETION_TEST_FAILURE", 503)

    monkeypatch.setattr(data_delete_api, "delete_all_user_data", fail)
    failed = await client.post(
        "/v1/data/delete",
        json={
            "request_id": str(request_id),
            "confirmation": "DELETE_MY_DATA",
        },
    )
    assert failed.status_code == 503
    event = _event(caplog, "data_deletion.failed")
    assert event["error_code"] == "DATA_DELETION_TEST_FAILURE"
    assert event["status_code"] == 503
    assert event["retryable"] is True


@pytest.mark.asyncio
async def test_account_delete_progress_and_failure_telemetry(
    client,
    monkeypatch,
    caplog,
    deletion_api_overrides,
):
    del deletion_api_overrides
    caplog.set_level(logging.INFO, logger=LOGGER)
    request_id = uuid4()

    monkeypatch.setattr(
        account_delete_api,
        "delete_current_account",
        lambda *a, **k: AccountDeletionResult(
            request_id=request_id,
            data_deletion_status=None,
            completed=False,
            retry_after_seconds=None,
            deleted_counts={"PRIVATE_ACCOUNT_RESOURCE_SENTINEL": 7},
        ),
    )
    response = await client.post(
        "/v1/account/delete",
        json={
            "request_id": str(request_id),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": False,
        },
    )
    assert response.status_code == 202
    progress = _event(caplog, "account_deletion.progress")
    assert progress["operation_request_id"] == str(request_id)
    assert progress["operation_status"] == "ACCOUNT_GATE_ACTIVE"
    assert progress["completed"] is False
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "PRIVATE_ACCOUNT_RESOURCE_SENTINEL" not in rendered

    caplog.clear()

    def fail(*args, **kwargs):
        del args, kwargs
        raise AccountDeletionError("ACCOUNT_DELETION_TEST_FAILURE", 423)

    monkeypatch.setattr(account_delete_api, "delete_current_account", fail)
    failed = await client.post(
        "/v1/account/delete",
        json={
            "request_id": str(request_id),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": False,
        },
    )
    assert failed.status_code == 423
    event = _event(caplog, "account_deletion.failed")
    assert event["error_code"] == "ACCOUNT_DELETION_TEST_FAILURE"
    assert event["status_code"] == 423
    assert event["retryable"] is True
