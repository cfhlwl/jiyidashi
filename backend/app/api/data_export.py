from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.export_models import UserExportJob, UserExportStatus
from app.maintenance_job_models import MaintenanceJobType
from app.models import User
from app.schemas import SignedTransfer
from app.services.api_abuse import enforce_authenticated_api_rate
from app.services.auth_rate_limit import ApiRouteClass
from app.services.maintenance_jobs import enqueue_maintenance_job
from app.services.object_storage import (
    ObjectStorage,
    ObjectStorageError,
    get_object_storage,
)

router = APIRouter(prefix="/export", tags=["export"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]
Storage = Annotated[ObjectStorage, Depends(get_object_storage)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


class ExportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    format_version: str
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    artifact_size_bytes: int | None
    artifact_sha256: str | None
    expires_at: datetime | None
    error_code: str | None
    revision: int


class ExportDownloadResponse(BaseModel):
    export_job_id: UUID
    artifact_size_bytes: int
    artifact_sha256: str
    artifact_expires_at: datetime
    download: SignedTransfer


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _owned_job(db: Session, *, owner_user_id: UUID, job_id: UUID) -> UserExportJob:
    job = db.scalar(
        select(UserExportJob).where(
            UserExportJob.id == job_id,
            UserExportJob.owner_user_id == owner_user_id,
        )
    )
    if job is None:
        # Owner-scoped 404 avoids turning export IDs into a cross-account oracle.
        raise HTTPException(status_code=404, detail="EXPORT_JOB_NOT_FOUND")
    return job


@router.get("/data")
def legacy_export_migration(
    response: Response,
    user_id: CurrentUser,
) -> dict[str, str]:
    del user_id
    _no_store(response)
    response.status_code = status.HTTP_410_GONE
    return {
        "detail": "EXPORT_ASYNC_REQUIRED",
        "create_path": "/v1/export/jobs",
    }


@router.post(
    "/jobs",
    response_model=ExportJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_export_job(
    request: Request,
    response: Response,
    user_id: CurrentUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> UserExportJob:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.EXPENSIVE_EXPORT,
    )
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")

    existing = db.scalar(
        select(UserExportJob).where(
            UserExportJob.owner_user_id == user_id,
            UserExportJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        _no_store(response)
        return existing

    job = UserExportJob(
        owner_user_id=user_id,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    try:
        db.flush()
        enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.EXPORT,
            dedupe_key=f"export:{job.id}",
            owner_user_id=user_id,
            resource_key=f"user-export:{job.id}",
            payload={"action": "GENERATE", "export_job_id": str(job.id)},
            max_attempts=10,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(UserExportJob).where(
                UserExportJob.owner_user_id == user_id,
                UserExportJob.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        job = existing

    _no_store(response)
    return job


@router.get("/jobs/{job_id}", response_model=ExportJobRead)
def get_export_job(
    job_id: UUID,
    response: Response,
    user_id: CurrentUser,
    db: DbSession,
) -> UserExportJob:
    job = _owned_job(db, owner_user_id=user_id, job_id=job_id)
    _no_store(response)
    return job


@router.get(
    "/jobs/{job_id}/download",
    response_model=ExportDownloadResponse,
)
def download_export_job(
    job_id: UUID,
    response: Response,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> ExportDownloadResponse:
    job = _owned_job(db, owner_user_id=user_id, job_id=job_id)
    if job.status != UserExportStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="EXPORT_NOT_COMPLETED")
    now = datetime.now(UTC)
    if job.expires_at is None or job.expires_at <= now:
        raise HTTPException(status_code=410, detail="EXPORT_EXPIRED")
    if (
        not job.artifact_object_key
        or job.artifact_size_bytes is None
        or not job.artifact_sha256
    ):
        raise HTTPException(status_code=409, detail="EXPORT_ARTIFACT_NOT_PUBLISHED")

    try:
        transfer = storage.sign_download(job.artifact_object_key)
    except ObjectStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="EXPORT_DOWNLOAD_SIGNING_FAILED",
        ) from exc

    _no_store(response)
    return ExportDownloadResponse(
        export_job_id=job.id,
        artifact_size_bytes=job.artifact_size_bytes,
        artifact_sha256=job.artifact_sha256,
        artifact_expires_at=job.expires_at,
        download=SignedTransfer(
            method=transfer.method,
            url=transfer.url,
            headers=transfer.headers,
            expires_at=transfer.expires_at,
        ),
    )
