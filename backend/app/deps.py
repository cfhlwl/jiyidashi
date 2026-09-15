from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

bearer = HTTPBearer()
BearerCredentials = Annotated[HTTPAuthorizationCredentials, Depends(bearer)]


def get_current_user_id(credentials: BearerCredentials) -> UUID:
    return decode_access_token(credentials.credentials)
