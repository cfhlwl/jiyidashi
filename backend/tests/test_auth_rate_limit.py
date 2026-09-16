import pytest
from fastapi import HTTPException

from app.core.db import SessionLocal
from app.services import auth_rate_limit


def test_registration_ip_window_returns_429(client, monkeypatch):
    # [人工注释][S1-FIX-003] 直接验证数据库级 IP bucket：达到窗口额度后必须在 Argon2 前 429 并给 Retry-After。
    monkeypatch.setattr(auth_rate_limit.settings, "auth_register_ip_limit", 2)
    client_ip = "198.51.100.77"

    with SessionLocal() as db:
        auth_rate_limit.consume_registration_attempt(db, client_ip)
        auth_rate_limit.consume_registration_attempt(db, client_ip)
        with pytest.raises(HTTPException) as exc_info:
            auth_rate_limit.consume_registration_attempt(db, client_ip)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "AUTH_RATE_LIMITED"
    assert int(exc_info.value.headers["Retry-After"]) >= 1


def test_rate_limit_bucket_does_not_store_raw_identifier(client):
    raw_value = "203.0.113.44"
    with SessionLocal() as db:
        auth_rate_limit.consume_registration_attempt(db, raw_value)
        key = auth_rate_limit._bucket_key("register_ip", raw_value)

        # [人工注释][S1-FIX-003] 数据库只保存固定长度 HMAC key，不保存原始 IP / 邮箱标识。
        assert len(key) == 64
        assert raw_value not in key
