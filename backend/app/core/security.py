from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    jti: UUID
    issued_at: datetime
    expires_at: datetime


def create_access_token(user_id: UUID, session_id: UUID | None = None) -> str:
    """Create a short-lived public access JWT bound to a durable session."""

    now = datetime.now(UTC)
    bound_session_id = session_id or user_id
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "jti": str(uuid4()),
        "session_id": str(bound_session_id),
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.access_token_minutes)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token_claims(token: str) -> AccessTokenClaims:
    """Validate the complete public JWT contract.

    A cryptographically valid token without issuer/audience/session binding is not a
    production access credential.
    """

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": [
                    "iss",
                    "aud",
                    "sub",
                    "jti",
                    "session_id",
                    "iat",
                    "exp",
                ]
            },
        )
        user_id = UUID(str(payload["sub"]))
        session_id = UUID(str(payload["session_id"]))
        jti = UUID(str(payload["jti"]))
        issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
        if expires_at <= issued_at:
            raise ValueError("invalid lifetime")
        return AccessTokenClaims(
            user_id=user_id,
            session_id=session_id,
            jti=jti,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_ACCESS_TOKEN",
        ) from exc


def decode_access_token(token: str) -> UUID:
    """Compatibility helper for tests/callers that only need the authenticated subject."""

    return decode_access_token_claims(token).user_id
