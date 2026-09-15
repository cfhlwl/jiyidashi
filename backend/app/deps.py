from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

bearer = HTTPBearer(auto_error=True)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> UUID:
    return decode_access_token(credentials.credentials)
