from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings
from app.core.db import SessionLocal
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import User
from app.services.admin_projection_service import (
    dashboard_projection,
    system_health_projection,
)


def _configured_settings() -> Settings:
    return Settings(
        storage_backend="s3",
        storage_bucket="private-bucket",
        storage_access_key_id="access",
        storage_secret_access_key="secret",
        ai_provider="openai",
        ai_api_key="ai-key",
        ai_model="reviewed-model",
        asr_provider="openai",
        asr_api_key="asr-key",
        asr_model="reviewed-asr",
        embedding_provider="openai",
        embedding_api_key="embedding-key",
    )


def test_configured_external_services_are_unverified_without_runtime_evidence():
    cfg = _configured_settings()
    observed = datetime.now(UTC)
    with SessionLocal() as db:
        dashboard = dashboard_projection(db, settings=cfg, now=observed)
        external = {
            item.key: (item.status, item.detail)
            for item in dashboard.services
            if item.key in {"storage", "ai", "asr", "embedding"}
        }
        assert external == {
            "storage": ("UNVERIFIED", "已配置 / 未验证"),
            "ai": ("UNVERIFIED", "已配置 / 未验证"),
            "asr": ("UNVERIFIED", "已配置 / 未验证"),
            "embedding": ("UNVERIFIED", "已配置 / 未验证"),
        }

        health = system_health_projection(db, settings=cfg)
        assert health.storage_status == "已配置 / 未验证"
        assert health.ai_status == "已配置 / 未验证"
        assert health.asr_status == "已配置 / 未验证"
        assert health.embedding_status == "已配置 / 未验证"


def test_recent_validated_storage_completion_is_real_health_evidence():
    cfg = _configured_settings()
    now = datetime.now(UTC)
    with SessionLocal() as db:
        user = User(nickname="health evidence")
        db.add(user)
        db.flush()
        db.add(
            MediaAsset(
                user_id=user.id,
                client_upload_id=uuid4(),
                kind=MediaKind.IMAGE,
                status=MediaStatus.READY,
                upload_object_key=f"staging/{uuid4()}",
                object_key=f"media/{uuid4()}",
                content_type="image/jpeg",
                size_bytes=128,
                storage_etag="etag",
                created_at=now - timedelta(minutes=2),
                completed_at=now - timedelta(minutes=1),
            )
        )
        db.commit()

        health = system_health_projection(db, settings=cfg)
        assert health.storage_status == "正常（有真实近期运行证据）"
