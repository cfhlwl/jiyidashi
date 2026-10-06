from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from uuid import UUID

from app.core.config import Settings, get_settings


class CursorInvalid(ValueError):
    pass


@dataclass(frozen=True)
class ObjectCursor:
    normalized_name: str
    object_id: UUID


def _sign(payload: bytes, settings: Settings) -> bytes:
    return hmac.new(
        settings.jwt_secret.encode(),
        b"api001:cursor:" + payload,
        hashlib.sha256,
    ).digest()


def encode_object_cursor(
    *,
    owner_user_id: UUID,
    normalized_name: str,
    object_id: UUID,
    settings: Settings | None = None,
) -> str:
    cfg = settings or get_settings()
    body = json.dumps(
        {
            "v": 1,
            "e": "objects-page-v1",
            "o": str(owner_user_id),
            "n": normalized_name,
            "i": str(object_id),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    body_token = base64.urlsafe_b64encode(body).decode().rstrip("=")
    signature_token = base64.urlsafe_b64encode(_sign(body, cfg)).decode().rstrip("=")
    return f"{body_token}.{signature_token}"


def decode_object_cursor(
    value: str,
    *,
    owner_user_id: UUID,
    settings: Settings | None = None,
) -> ObjectCursor:
    cfg = settings or get_settings()
    if not value or len(value) > 2048:
        raise CursorInvalid("OBJECT_CURSOR_INVALID")
    try:
        body_token, signature_token = value.split(".", 1)
        body = base64.urlsafe_b64decode(
            body_token + "=" * (-len(body_token) % 4)
        )
        signature = base64.urlsafe_b64decode(
            signature_token + "=" * (-len(signature_token) % 4)
        )
        if not hmac.compare_digest(signature, _sign(body, cfg)):
            raise CursorInvalid("OBJECT_CURSOR_INVALID")
        payload = json.loads(body)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CursorInvalid("OBJECT_CURSOR_INVALID") from exc

    if not isinstance(payload, dict):
        raise CursorInvalid("OBJECT_CURSOR_INVALID")
    if payload.get("v") != 1 or payload.get("e") != "objects-page-v1":
        raise CursorInvalid("OBJECT_CURSOR_INVALID")
    if payload.get("o") != str(owner_user_id):
        raise CursorInvalid("OBJECT_CURSOR_INVALID")

    normalized_name = payload.get("n")
    raw_id = payload.get("i")
    if not isinstance(normalized_name, str) or not normalized_name:
        raise CursorInvalid("OBJECT_CURSOR_INVALID")
    if len(normalized_name) > 160:
        raise CursorInvalid("OBJECT_CURSOR_INVALID")
    try:
        object_id = UUID(str(raw_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CursorInvalid("OBJECT_CURSOR_INVALID") from exc

    return ObjectCursor(
        normalized_name=normalized_name,
        object_id=object_id,
    )
