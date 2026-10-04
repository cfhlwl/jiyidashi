from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.services.auth_rate_limit import (
    ApiRouteClass,
    consume_authenticated_api_attempt,
)


def enforce_authenticated_api_rate(
    db: Session,
    *,
    user_id: UUID,
    request: Request,
    route_class: ApiRouteClass,
) -> None:
    # Trust only the ASGI peer address here. Proxy trust remains deployment-owned;
    # clients cannot supply X-Forwarded-For as rate-limit authority.
    client_ip = request.client.host if request.client is not None else "unknown"
    # SEC-016 rate-limit authority must commit independently from the
    # request's business transaction. Reusing the request Session would let the
    # limiter's commit/rollback change media, summary, export, or other domain
    # transaction semantics.
    with Session(bind=db.get_bind()) as rate_db:
        consume_authenticated_api_attempt(
            rate_db,
            user_id=user_id,
            client_ip=client_ip,
            route_class=route_class,
        )
