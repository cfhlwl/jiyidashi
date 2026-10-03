from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin_deps import AdminPrincipal, require_admin_mutation, require_admin_roles
from app.admin_models import AdminRole, ProviderService
from app.admin_schemas import (
    AdminEmbeddingBackfillRead,
    AdminEmbeddingBackfillRequest,
    AdminProviderConfigListRead,
    AdminProviderConfigRead,
    AdminProviderConfigWrite,
)
from app.core.db import get_db
from app.services.admin_provider_service import (
    embedding_backfill_status,
    read_provider_configurations,
    run_embedding_backfill_batch,
    update_provider_configuration,
)
from app.services.admin_security import AdminOperationError

router = APIRouter(tags=["admin-provider-settings"])
DbSession = Annotated[Session, Depends(get_db)]
AnyAdminRead = Annotated[
    AdminPrincipal,
    Depends(
        require_admin_roles(
            AdminRole.SUPER_ADMIN,
            AdminRole.OPERATOR,
            AdminRole.SUPPORT_READONLY,
        )
    ),
]
SuperAdminMutation = Annotated[
    AdminPrincipal,
    Depends(require_admin_mutation(AdminRole.SUPER_ADMIN)),
]


def _raise(exc: AdminOperationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _service(value: str) -> ProviderService:
    try:
        return ProviderService(value.strip().upper())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="ADMIN_PROVIDER_NOT_FOUND") from exc


def _read_one(db: Session, service: ProviderService) -> AdminProviderConfigRead:
    payload = read_provider_configurations(db)
    return next(item for item in payload.services if item.service == service)


@router.get("/settings/providers", response_model=AdminProviderConfigListRead)
def providers(
    db: DbSession,
    _: AnyAdminRead,
) -> AdminProviderConfigListRead:
    try:
        return read_provider_configurations(db)
    except AdminOperationError as exc:
        _raise(exc)


@router.put(
    "/settings/providers/{service}",
    response_model=AdminProviderConfigRead,
)
def update_provider(
    service: str,
    payload: AdminProviderConfigWrite,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminProviderConfigRead:
    provider_service = _service(service)
    try:
        update_provider_configuration(
            db,
            actor=principal.account,
            service=provider_service,
            payload=payload,
        )
        return _read_one(db, provider_service)
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)


@router.get(
    "/settings/providers/embedding/backfill",
    response_model=AdminEmbeddingBackfillRead,
)
def embedding_backfill(
    db: DbSession,
    _: AnyAdminRead,
) -> AdminEmbeddingBackfillRead:
    return embedding_backfill_status(db)


@router.post(
    "/settings/providers/embedding/backfill",
    response_model=AdminEmbeddingBackfillRead,
)
async def continue_embedding_backfill(
    payload: AdminEmbeddingBackfillRequest,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminEmbeddingBackfillRead:
    try:
        return await run_embedding_backfill_batch(
            db,
            actor=principal.account,
            payload=payload,
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
