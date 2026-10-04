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


def _has_explicit_authenticated_rate_policy(request: Request) -> bool:
    path = request.url.path
    method = request.method.upper()

    if path.endswith("/media/uploads"):
        return True
    if "/media/" in path and any(
        path.endswith(suffix)
        for suffix in (
            "/complete",
            "/download",
            "/ocr",
            "/vision",
            "/voice-memory",
        )
    ):
        return True
    if "/memory/summaries/" in path:
        return True
    if "/life-stages/" in path and path.endswith("/reason"):
        return True
    if method == "POST" and path.endswith("/memoirs/annual"):
        return True
    if (
        method == "POST"
        and "/memoirs/life/stages/" in path
        and not path.endswith("/memoirs/life/stages")
    ):
        return True
    if path.endswith("/export/data"):
        return True
    return False


def enforce_default_authenticated_api_rate(
    db: Session,
    *,
    user_id: UUID,
    request: Request,
) -> None:
    # Specialized media/AI/export routes keep their explicit stronger classes.
    # Every other authenticated public API is covered centrally so new ordinary
    # endpoints cannot silently bypass NORMAL_READ/NORMAL_MUTATION.
    if _has_explicit_authenticated_rate_policy(request):
        return
    route_class = (
        ApiRouteClass.NORMAL_READ
        if request.method.upper() in {"GET", "HEAD", "OPTIONS"}
        else ApiRouteClass.NORMAL_MUTATION
    )
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=route_class,
    )
