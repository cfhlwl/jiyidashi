from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()

# access token 的 subject 只承载服务端已认证用户 UUID；客户端输入从不拥有身份决定权。
# 签名算法、密钥与有效期均由服务端配置控制，任何 decode/expiry/subject 异常统一 fail closed 为 401。


def create_access_token(user_id: UUID) -> str:
    # iat/exp 由服务端当前 UTC 时间生成；调用方只能提供已经认证后的 UUID，
    # 不能自定义 token 生命周期。
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID:
    # 验签、过期校验和 subject UUID 解析属于同一个认证边界；任一步失败都不降级为匿名/客户端身份。
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        subject = payload.get("sub")
        if not subject:
            raise ValueError("missing subject")
        return UUID(subject)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_ACCESS_TOKEN",
        ) from exc
