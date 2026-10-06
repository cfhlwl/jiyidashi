from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, union
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.core.config import get_settings
from app.core.db import (
    SessionLocal,
    UserDataRequestStale,
    engine,
    hold_user_data_disclosure_handoff,
)
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.export_models import UserExportJob, UserExportStatus
from app.maintenance.location_retention import maintain_discovered_location_owner
from app.maintenance_job_models import MaintenanceJob, MaintenanceJobType
from app.media_models import MediaAsset, MediaStatus
from app.models import LocationDerivationState, LocationPoint, User
from app.security_models import SecurityAlert, SecurityAlertDeliveryStatus
from app.services.account_deletion_service import (
    AccountDeletionError,
    progress_prepared_account_deletion,
)
from app.services.analytics_service import prune_analytics
from app.services.data_deletion_service import (
    MAX_OUTSTANDING_UPLOAD_TTL_SECONDS,
    DataDeletionError,
    delete_all_user_data,
)
from app.services.export_service import (
    EXPORT_CONTENT_TYPE,
    ExportExecutionError,
    assert_export_attempt_current,
    begin_export_attempt,
    cleanup_export_artifact,
    export_attempt_object_key,
    export_object_prefix,
    generate_export_file,
    mark_export_attempt_failed,
    publish_export_artifact,
    remove_temp_file,
)
from app.services.maintenance_jobs import (
    MaintenanceJobClaim,
    MaintenanceLeaseLost,
    assert_maintenance_claim_current,
    enqueue_maintenance_job,
    fence_owner_maintenance_jobs_for_deletion,
    renew_maintenance_claim,
)
from app.services.object_storage import (
    DisabledObjectStorage,
    ObjectStorage,
    ObjectStorageError,
    PresignedTransfer,
    StoredObject,
    get_object_storage,
)
from app.services.security_alerting import deliver_security_alert

SCHEDULER_CATEGORY_LIMIT = 200
SCHEDULER_SCAN_LIMIT = 2000
ANALYTICS_RETENTION_BATCH_SIZE = 1000
MEDIA_CLEANUP_MAX_ATTEMPTS = 20
DELETION_MAX_ATTEMPTS = 50
ANALYTICS_MAX_ATTEMPTS = 100
EXPORT_MAX_ATTEMPTS = 10


class RetryableMaintenanceError(RuntimeError):
    def __init__(self, code: str, *, retry_after_seconds: int | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


class TerminalMaintenanceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SchedulerResult:
    enqueued: int
    existing: int


class ClaimAuthority:
    """Database-backed execution authority for one claimed maintenance job."""

    def __init__(
        self,
        claim: MaintenanceJobClaim,
        *,
        lease_seconds: int | None = None,
    ):
        self.claim = claim
        if lease_seconds is None:
            remaining = (
                _as_utc(claim.lease_expires_at) - datetime.now(UTC)
            ).total_seconds()
            lease_seconds = max(1, math.ceil(remaining))
        self.lease_seconds = lease_seconds

    def check(self) -> None:
        with SessionLocal() as db:
            renew_maintenance_claim(
                db,
                job_id=self.claim.id,
                claim_token=self.claim.claim_token,
                lease_seconds=self.lease_seconds,
            )
            db.commit()

    def assert_current(self) -> None:
        with SessionLocal() as db:
            assert_maintenance_claim_current(
                db,
                job_id=self.claim.id,
                claim_token=self.claim.claim_token,
            )
            db.rollback()

    def run_with_heartbeat(self, operation: Callable[[], object]):
        self.check()
        stop = threading.Event()
        heartbeat_error: list[BaseException] = []
        interval = max(0.1, min(5.0, self.lease_seconds / 3))

        def heartbeat() -> None:
            while not stop.wait(interval):
                try:
                    self.check()
                except BaseException as exc:
                    heartbeat_error.append(exc)
                    stop.set()
                    return

        thread = threading.Thread(
            target=heartbeat,
            name=f"maintenance-heartbeat-{self.claim.id}",
            daemon=True,
        )
        thread.start()
        operation_error: BaseException | None = None
        result = None
        try:
            result = operation()
        except BaseException as exc:
            operation_error = exc
        finally:
            stop.set()
            thread.join(timeout=max(1.0, interval * 2))

        if heartbeat_error:
            raise heartbeat_error[0]
        self.check()
        if operation_error is not None:
            raise operation_error
        return result


class ClaimFencedObjectStorage:
    """Wrap object-store I/O with before/after durable claim checks."""

    def __init__(self, inner: ObjectStorage, authority: ClaimAuthority):
        self._inner = inner
        self._authority = authority

    def _call(self, operation: Callable[[], object]):
        self._authority.check()
        result = operation()
        self._authority.check()
        return result

    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer:
        return self._call(
            lambda: self._inner.sign_upload(object_key, content_type)
        )

    def sign_download(self, object_key: str) -> PresignedTransfer:
        return self._call(lambda: self._inner.sign_download(object_key))

    def stat_object(self, object_key: str) -> StoredObject:
        return self._call(lambda: self._inner.stat_object(object_key))

    def read_prefix(self, object_key: str, max_bytes: int) -> bytes:
        return self._call(lambda: self._inner.read_prefix(object_key, max_bytes))

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        return self._call(lambda: self._inner.read_object(object_key, max_bytes))

    def upload_file(
        self,
        local_path: str,
        object_key: str,
        content_type: str,
        sha256: str,
    ) -> StoredObject:
        return self._authority.run_with_heartbeat(
            lambda: self._inner.upload_file(
                local_path,
                object_key,
                content_type,
                sha256,
            )
        )

    def promote_object(self, source_key: str, destination_key: str) -> None:
        self._call(lambda: self._inner.promote_object(source_key, destination_key))

    def delete_object(self, object_key: str) -> None:
        self._call(lambda: self._inner.delete_object(object_key))

    def iter_object_keys(self, prefix: str) -> Iterator[str]:
        self._authority.check()
        try:
            for key in self._inner.iter_object_keys(prefix):
                self._authority.check()
                yield key
        finally:
            self._authority.check()


def _storage_for_claim(authority: ClaimAuthority) -> ObjectStorage:
    storage = get_object_storage()
    if isinstance(storage, DisabledObjectStorage):
        return storage
    return ClaimFencedObjectStorage(storage, authority)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _retry_delay(deadline: datetime | None, *, default: int = 30) -> int:
    if deadline is None:
        return default
    return max(
        1,
        min(
            24 * 60 * 60,
            math.ceil((_as_utc(deadline) - datetime.now(UTC)).total_seconds()),
        ),
    )


def _cancel_other_owner_jobs(
    *,
    owner_user_id: UUID,
    current_job_id: UUID,
) -> int:
    with SessionLocal() as db:
        cancelled = fence_owner_maintenance_jobs_for_deletion(
            db,
            owner_user_id=owner_user_id,
            preserve_job_id=current_job_id,
        )
        db.commit()
        return cancelled


def _require_owner(claim: MaintenanceJobClaim) -> UUID:
    if claim.owner_user_id is None:
        raise TerminalMaintenanceError("MAINTENANCE_OWNER_REQUIRED")
    return claim.owner_user_id


def handle_data_delete(claim: MaintenanceJobClaim) -> None:
    owner_user_id = _require_owner(claim)
    authority = ClaimAuthority(claim)
    authority.check()

    with SessionLocal() as db:
        account_gate = db.scalar(
            select(AccountDeletionOperation.id)
            .where(AccountDeletionOperation.user_id == owner_user_id)
            .limit(1)
        )
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.id == UUID(str(claim.payload.get("operation_id"))),
                DataDeletionOperation.user_id == owner_user_id,
            )
        )
        if account_gate is not None:
            db.rollback()
            return
        if operation is None or operation.status == DataDeletionStatus.COMPLETED:
            db.rollback()
            return
        request_id = operation.request_id
        db.rollback()

    _cancel_other_owner_jobs(
        owner_user_id=owner_user_id,
        current_job_id=claim.id,
    )
    authority.check()

    try:
        with SessionLocal() as db:
            result = delete_all_user_data(
                db,
                user_id=owner_user_id,
                request_id=request_id,
                storage=_storage_for_claim(authority),
                authority_check=authority.check,
                maintenance_job_id=claim.id,
                maintenance_claim_token=claim.claim_token,
            )
    except DataDeletionError as exc:
        if exc.code == "USER_NOT_FOUND":
            return
        if exc.status_code >= 500 or exc.status_code in {409, 423, 429}:
            raise RetryableMaintenanceError(
                exc.code,
                retry_after_seconds=30,
            ) from exc
        raise TerminalMaintenanceError(exc.code) from exc

    if not result.completed:
        raise RetryableMaintenanceError(
            f"DATA_DELETE_{result.status.value}",
            retry_after_seconds=result.retry_after_seconds or 30,
        )


def handle_account_delete(claim: MaintenanceJobClaim) -> None:
    if claim.owner_user_id is None:
        # Account finalization scrubs the current job in the same transaction that
        # deletes User. A crash after that commit can only leave this anonymous
        # RUNNING receipt; reclaiming it is a pure terminal-success cleanup.
        if (
            claim.dedupe_key is None
            and claim.resource_key is None
            and not claim.payload
        ):
            return
        raise TerminalMaintenanceError("MAINTENANCE_OWNER_REQUIRED")
    owner_user_id = claim.owner_user_id
    authority = ClaimAuthority(claim)
    authority.check()
    _cancel_other_owner_jobs(
        owner_user_id=owner_user_id,
        current_job_id=claim.id,
    )
    authority.check()

    try:
        with SessionLocal() as db:
            result = progress_prepared_account_deletion(
                db,
                user_id=owner_user_id,
                operation_id=UUID(str(claim.payload.get("operation_id"))),
                storage=_storage_for_claim(authority),
                authority_check=authority.check,
                maintenance_job_id=claim.id,
            )
    except (AccountDeletionError, DataDeletionError) as exc:
        if getattr(exc, "code", "") == "USER_NOT_FOUND":
            return
        status_code = getattr(exc, "status_code", 500)
        if status_code >= 500 or status_code in {409, 423, 429}:
            raise RetryableMaintenanceError(
                getattr(exc, "code", "ACCOUNT_DELETE_RETRY"),
                retry_after_seconds=30,
            ) from exc
        raise TerminalMaintenanceError(
            getattr(exc, "code", "ACCOUNT_DELETE_FAILED")
        ) from exc

    if result is None or result.completed:
        return
    raise RetryableMaintenanceError(
        "ACCOUNT_DELETE_WAITING",
        retry_after_seconds=result.retry_after_seconds or 30,
    )


def _media_cleanup_due_at(asset: MediaAsset) -> datetime:
    settings = get_settings()
    capability_expiry = asset.upload_capability_expires_at
    if capability_expiry is None:
        capability_expiry = _as_utc(asset.created_at) + timedelta(
            seconds=MAX_OUTSTANDING_UPLOAD_TTL_SECONDS
        )
    return _as_utc(capability_expiry) + timedelta(
        seconds=settings.storage_delete_settle_seconds
    )


def handle_media_pending_cleanup(claim: MaintenanceJobClaim) -> None:
    owner_user_id = _require_owner(claim)
    authority = ClaimAuthority(claim)
    authority.check()
    media_id = UUID(str(claim.payload.get("media_id")))
    frozen_object_key = str(claim.payload.get("upload_object_key") or "")
    if not frozen_object_key:
        raise TerminalMaintenanceError("MEDIA_CLEANUP_OBJECT_KEY_MISSING")

    should_delete_storage = True
    with SessionLocal() as db:
        user_exists = db.scalar(
            select(User.id)
            .where(User.id == owner_user_id)
            .with_for_update(read=True, key_share=True)
        )
        if user_exists is None:
            db.rollback()
            return
        destructive = db.scalar(
            select(AccountDeletionOperation.id)
            .where(AccountDeletionOperation.user_id == owner_user_id)
            .limit(1)
        )
        if destructive is None:
            destructive = db.scalar(
                select(DataDeletionOperation.id)
                .where(
                    DataDeletionOperation.user_id == owner_user_id,
                    DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
                )
                .limit(1)
            )
        if destructive is not None:
            db.rollback()
            return

        asset = db.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.id == media_id,
                MediaAsset.user_id == owner_user_id,
            )
            .with_for_update()
        )
        if asset is not None:
            if asset.upload_object_key != frozen_object_key:
                db.rollback()
                raise TerminalMaintenanceError("MEDIA_CLEANUP_IDENTITY_MISMATCH")
            if asset.status == MediaStatus.PENDING:
                due_at = _media_cleanup_due_at(asset)
                if due_at > datetime.now(UTC):
                    db.rollback()
                    raise RetryableMaintenanceError(
                        "MEDIA_CLEANUP_CAPABILITY_ACTIVE",
                        retry_after_seconds=_retry_delay(due_at),
                    )
                db.delete(asset)
                authority.check()
                db.commit()
            else:
                db.rollback()
        else:
            db.rollback()

    if should_delete_storage:
        storage = _storage_for_claim(authority)
        try:
            authority.check()
            storage.delete_object(frozen_object_key)
            authority.check()
        except ObjectStorageError as exc:
            raise RetryableMaintenanceError(
                "MEDIA_CLEANUP_STORAGE_UNAVAILABLE",
                retry_after_seconds=30,
            ) from exc


def handle_export(claim: MaintenanceJobClaim) -> None:
    owner_user_id = _require_owner(claim)
    authority = ClaimAuthority(claim)
    authority.check()
    try:
        export_job_id = UUID(str(claim.payload.get("export_job_id")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise TerminalMaintenanceError("EXPORT_JOB_PAYLOAD_INVALID") from exc

    action = str(claim.payload.get("action") or "GENERATE")
    raw_storage = get_object_storage()
    storage = _storage_for_claim(authority)

    if action == "CLEANUP":
        try:
            cleanup_export_artifact(
                job_id=export_job_id,
                owner_user_id=owner_user_id,
                storage=storage,
                authority_check=authority.check,
            )
        except ExportExecutionError as exc:
            if exc.retryable:
                raise RetryableMaintenanceError(
                    exc.code,
                    retry_after_seconds=30,
                ) from exc
            raise TerminalMaintenanceError(exc.code) from exc
        except ObjectStorageError as exc:
            raise RetryableMaintenanceError(
                "EXPORT_CLEANUP_STORAGE_UNAVAILABLE",
                retry_after_seconds=30,
            ) from exc
        return

    if action != "GENERATE":
        raise TerminalMaintenanceError("EXPORT_JOB_ACTION_INVALID")

    revision = begin_export_attempt(
        job_id=export_job_id,
        owner_user_id=owner_user_id,
    )
    if revision is None:
        return

    generated = None
    object_key = None
    terminal = False
    try:
        # A retry first removes stale attempt objects for this job. Only the
        # currently published key is ever returned to users.
        prefix = export_object_prefix(owner_user_id, export_job_id)
        for stale_key in storage.iter_object_keys(prefix):
            authority.check()
            storage.delete_object(stale_key)

        generated = generate_export_file(
            owner_user_id=owner_user_id,
            authority_check=authority.check,
        )
        authority.check()
        object_key = export_attempt_object_key(
            owner_user_id=owner_user_id,
            job_id=export_job_id,
            revision=revision,
            attempt_token=claim.claim_token,
        )
        # Share the canonical destructive handoff across the entire physical
        # upload -> verify -> publish boundary. Data/Account Delete takes the matching
        # exclusive advisory lock before it can establish the destructive gate, so its
        # final storage inventory cannot run ahead of an in-flight export upload.
        with hold_user_data_disclosure_handoff(
            engine,
            user_id=owner_user_id,
        ):
            # Re-check after acquiring the shared handoff. If deletion won the race,
            # its committed gate/maintenance fencing must stop this stale attempt
            # before any new export object is written.
            authority.check()
            assert_export_attempt_current(
                job_id=export_job_id,
                owner_user_id=owner_user_id,
                revision=revision,
            )
            stored = storage.upload_file(
                generated.path,
                object_key,
                EXPORT_CONTENT_TYPE,
                generated.sha256,
            )
            authority.check()
            if (
                stored.size_bytes != generated.size_bytes
                or stored.sha256 != generated.sha256
                or stored.content_type.split(";", 1)[0].strip().lower()
                != EXPORT_CONTENT_TYPE
            ):
                raise ExportExecutionError(
                    "EXPORT_ARTIFACT_VERIFICATION_FAILED",
                    retryable=True,
                )
            if not publish_export_artifact(
                job_id=export_job_id,
                owner_user_id=owner_user_id,
                revision=revision,
                object_key=object_key,
                size_bytes=generated.size_bytes,
                sha256=generated.sha256,
            ):
                raise ExportExecutionError("EXPORT_AUTHORITY_LOST", retryable=False)
        object_key = None
    except ExportExecutionError as exc:
        terminal = not exc.retryable or claim.attempt_count >= claim.max_attempts
        mark_export_attempt_failed(
            job_id=export_job_id,
            owner_user_id=owner_user_id,
            revision=revision,
            error_code=exc.code,
            terminal=terminal,
        )
        if terminal:
            raise TerminalMaintenanceError(exc.code) from exc
        raise RetryableMaintenanceError(
            exc.code,
            retry_after_seconds=30,
        ) from exc
    except ObjectStorageError as exc:
        terminal = claim.attempt_count >= claim.max_attempts
        mark_export_attempt_failed(
            job_id=export_job_id,
            owner_user_id=owner_user_id,
            revision=revision,
            error_code="EXPORT_STORAGE_UNAVAILABLE",
            terminal=terminal,
        )
        if terminal:
            raise TerminalMaintenanceError("EXPORT_STORAGE_UNAVAILABLE") from exc
        raise RetryableMaintenanceError(
            "EXPORT_STORAGE_UNAVAILABLE",
            retry_after_seconds=30,
        ) from exc
    except MaintenanceLeaseLost:
        terminal = claim.attempt_count >= claim.max_attempts
        mark_export_attempt_failed(
            job_id=export_job_id,
            owner_user_id=owner_user_id,
            revision=revision,
            error_code="EXPORT_MAINTENANCE_LEASE_LOST",
            terminal=terminal,
        )
        raise
    except OSError as exc:
        terminal = claim.attempt_count >= claim.max_attempts
        mark_export_attempt_failed(
            job_id=export_job_id,
            owner_user_id=owner_user_id,
            revision=revision,
            error_code="EXPORT_LOCAL_IO_FAILED",
            terminal=terminal,
        )
        if terminal:
            raise TerminalMaintenanceError("EXPORT_LOCAL_IO_FAILED") from exc
        raise RetryableMaintenanceError(
            "EXPORT_LOCAL_IO_FAILED",
            retry_after_seconds=30,
        ) from exc
    except Exception as exc:
        terminal = claim.attempt_count >= claim.max_attempts
        mark_export_attempt_failed(
            job_id=export_job_id,
            owner_user_id=owner_user_id,
            revision=revision,
            error_code="EXPORT_EXECUTION_FAILED",
            terminal=terminal,
        )
        if terminal:
            raise TerminalMaintenanceError("EXPORT_EXECUTION_FAILED") from exc
        raise RetryableMaintenanceError(
            "EXPORT_EXECUTION_FAILED",
            retry_after_seconds=30,
        ) from exc
    finally:
        remove_temp_file(None if generated is None else generated.path)
        if object_key is not None:
            # Attempt keys are unique to this maintenance claim. Best-effort direct
            # cleanup cannot delete a newer worker's published artifact.
            try:
                raw_storage.delete_object(object_key)
            except ObjectStorageError:
                pass


def handle_security_alert_delivery(claim: MaintenanceJobClaim) -> None:
    authority = ClaimAuthority(claim)
    authority.check()
    alert_id = UUID(str(claim.payload.get("alert_id")))

    with SessionLocal() as db:
        alert = db.get(SecurityAlert, alert_id)
        if alert is None:
            db.rollback()
            return
        if alert.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value:
            db.rollback()
            return
        if alert.delivery_status == SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value:
            db.rollback()
            raise TerminalMaintenanceError("SECURITY_ALERT_TERMINAL_FAILURE")
        if alert.next_retry_at is not None and _as_utc(alert.next_retry_at) > datetime.now(UTC):
            retry_at = alert.next_retry_at
            db.rollback()
            raise RetryableMaintenanceError(
                "SECURITY_ALERT_NOT_DUE",
                retry_after_seconds=_retry_delay(retry_at),
            )
        db.rollback()

    deliver_security_alert(
        engine,
        alert_id=str(alert_id),
        authority_check=authority.check,
    )
    authority.check()

    with SessionLocal() as db:
        alert = db.get(SecurityAlert, alert_id)
        if alert is None or alert.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value:
            db.rollback()
            return
        if alert.delivery_status == SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value:
            db.rollback()
            raise TerminalMaintenanceError("SECURITY_ALERT_TERMINAL_FAILURE")
        retry_at = alert.next_retry_at
        db.rollback()
    raise RetryableMaintenanceError(
        "SECURITY_ALERT_RETRYABLE_FAILURE",
        retry_after_seconds=_retry_delay(retry_at),
    )


def handle_analytics_retention(claim: MaintenanceJobClaim) -> None:
    authority = ClaimAuthority(claim)
    authority.check()
    try:
        retrieval_days = int(claim.payload["retrieval_days"])
        active_day_days = int(claim.payload["active_day_days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TerminalMaintenanceError(
            "ANALYTICS_RETENTION_PAYLOAD_INVALID"
        ) from exc
    with SessionLocal() as db:
        def assert_claim_in_transaction() -> None:
            assert_maintenance_claim_current(
                db,
                job_id=claim.id,
                claim_token=claim.claim_token,
            )

        retrieval_deleted, active_deleted = prune_analytics(
            db,
            retrieval_days=retrieval_days,
            active_day_days=active_day_days,
            batch_size=ANALYTICS_RETENTION_BATCH_SIZE,
            authority_check=assert_claim_in_transaction,
        )
    if (
        retrieval_deleted >= ANALYTICS_RETENTION_BATCH_SIZE
        or active_deleted >= ANALYTICS_RETENTION_BATCH_SIZE
    ):
        raise RetryableMaintenanceError(
            "ANALYTICS_RETENTION_CONTINUE",
            retry_after_seconds=1,
        )


def handle_location_retention(claim: MaintenanceJobClaim) -> None:
    owner_user_id = _require_owner(claim)
    authority = ClaimAuthority(claim)
    authority.check()
    try:
        maintain_discovered_location_owner(
            owner_user_id,
            authority_check=authority.check,
        )
    except UserDataRequestStale:
        # A destructive operation superseded this maintenance result.
        return


def default_maintenance_handlers() -> dict[str, Callable[[MaintenanceJobClaim], None]]:
    return {
        MaintenanceJobType.DATA_DELETE.value: handle_data_delete,
        MaintenanceJobType.ACCOUNT_DELETE.value: handle_account_delete,
        MaintenanceJobType.MEDIA_PENDING_CLEANUP.value: handle_media_pending_cleanup,
        MaintenanceJobType.SECURITY_ALERT_DELIVERY.value: handle_security_alert_delivery,
        MaintenanceJobType.ANALYTICS_RETENTION.value: handle_analytics_retention,
        MaintenanceJobType.LOCATION_RETENTION.value: handle_location_retention,
        MaintenanceJobType.EXPORT.value: handle_export,
    }


def _enqueue(
    db: Session,
    *,
    job_type: MaintenanceJobType,
    dedupe_key: str,
    owner_user_id: UUID | None = None,
    resource_key: str | None = None,
    payload: dict | None = None,
    max_attempts: int = 5,
    next_attempt_at: datetime | None = None,
) -> bool:
    _, created = enqueue_maintenance_job(
        db,
        job_type=job_type,
        dedupe_key=dedupe_key,
        owner_user_id=owner_user_id,
        resource_key=resource_key,
        payload=payload,
        max_attempts=max_attempts,
        next_attempt_at=next_attempt_at,
    )
    return created


def discover_and_enqueue_maintenance_jobs(
    *,
    now: datetime | None = None,
) -> SchedulerResult:
    observed_at = _as_utc(now or datetime.now(UTC))
    settings = get_settings()
    enqueued = 0
    existing = 0

    with SessionLocal() as db:
        linked_account_requests = select(
            AccountDeletionOperation.data_deletion_request_id
        )
        scheduled_data_owners = select(MaintenanceJob.owner_user_id).where(
            MaintenanceJob.job_type == MaintenanceJobType.DATA_DELETE.value,
            MaintenanceJob.owner_user_id.is_not(None),
        )
        data_operations = list(
            db.scalars(
                select(DataDeletionOperation)
                .where(
                    DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
                    DataDeletionOperation.request_id.not_in(linked_account_requests),
                    DataDeletionOperation.user_id.not_in(scheduled_data_owners),
                )
                .order_by(DataDeletionOperation.created_at.asc())
                .limit(SCHEDULER_CATEGORY_LIMIT)
            )
        )
        for operation in data_operations:
            created = _enqueue(
                db,
                job_type=MaintenanceJobType.DATA_DELETE,
                dedupe_key=f"data-delete:{operation.id}",
                owner_user_id=operation.user_id,
                resource_key=f"data-deletion:{operation.id}",
                payload={"operation_id": str(operation.id)},
                max_attempts=DELETION_MAX_ATTEMPTS,
                next_attempt_at=observed_at,
            )
            enqueued += int(created)
            existing += int(not created)

        scheduled_account_owners = select(MaintenanceJob.owner_user_id).where(
            MaintenanceJob.job_type == MaintenanceJobType.ACCOUNT_DELETE.value,
            MaintenanceJob.owner_user_id.is_not(None),
        )
        account_operations = list(
            db.scalars(
                select(AccountDeletionOperation)
                .where(
                    AccountDeletionOperation.local_cleanup_ready_at.is_not(None),
                    AccountDeletionOperation.user_id.not_in(scheduled_account_owners),
                )
                .order_by(AccountDeletionOperation.created_at.asc())
                .limit(SCHEDULER_CATEGORY_LIMIT)
            )
        )
        for operation in account_operations:
            created = _enqueue(
                db,
                job_type=MaintenanceJobType.ACCOUNT_DELETE,
                dedupe_key=f"account-delete:{operation.id}",
                owner_user_id=operation.user_id,
                resource_key=f"account-deletion:{operation.id}",
                payload={"operation_id": str(operation.id)},
                max_attempts=DELETION_MAX_ATTEMPTS,
                next_attempt_at=observed_at,
            )
            enqueued += int(created)
            existing += int(not created)

        active_account_users = select(AccountDeletionOperation.user_id)
        active_data_users = select(DataDeletionOperation.user_id).where(
            DataDeletionOperation.status != DataDeletionStatus.COMPLETED
        )
        pending_media = list(
            db.scalars(
                select(MediaAsset)
                .where(
                    MediaAsset.status == MediaStatus.PENDING,
                    MediaAsset.user_id.not_in(active_account_users),
                    MediaAsset.user_id.not_in(active_data_users),
                )
                .order_by(
                    func.coalesce(
                        MediaAsset.upload_capability_expires_at,
                        MediaAsset.created_at,
                    ).asc(),
                    MediaAsset.created_at.asc(),
                    MediaAsset.id.asc(),
                )
                .limit(SCHEDULER_SCAN_LIMIT)
            )
        )
        due_media = [
            (asset, _media_cleanup_due_at(asset))
            for asset in pending_media
            if _media_cleanup_due_at(asset) <= observed_at
        ]
        media_resource_keys = [f"media:{asset.id}" for asset, _ in due_media]
        scheduled_media_keys: set[str] = set()
        if media_resource_keys:
            scheduled_media_keys = set(
                db.scalars(
                    select(MaintenanceJob.resource_key).where(
                        MaintenanceJob.job_type
                        == MaintenanceJobType.MEDIA_PENDING_CLEANUP.value,
                        MaintenanceJob.resource_key.in_(media_resource_keys),
                    )
                )
            )
        media_added = 0
        for asset, due_at in due_media:
            resource_key = f"media:{asset.id}"
            if resource_key in scheduled_media_keys:
                existing += 1
                continue
            generation = int(
                _as_utc(
                    asset.upload_capability_expires_at or asset.created_at
                ).timestamp()
            )
            created = _enqueue(
                db,
                job_type=MaintenanceJobType.MEDIA_PENDING_CLEANUP,
                dedupe_key=f"media-cleanup:{asset.id}:{generation}",
                owner_user_id=asset.user_id,
                resource_key=resource_key,
                payload={
                    "media_id": str(asset.id),
                    "upload_object_key": asset.upload_object_key,
                },
                max_attempts=MEDIA_CLEANUP_MAX_ATTEMPTS,
                next_attempt_at=due_at,
            )
            enqueued += int(created)
            existing += int(not created)
            if created:
                media_added += 1
                scheduled_media_keys.add(resource_key)
                if media_added >= SCHEDULER_CATEGORY_LIMIT:
                    break

        due_alerts = list(
            db.scalars(
                select(SecurityAlert)
                .where(
                    SecurityAlert.delivery_status.in_(
                        (
                            SecurityAlertDeliveryStatus.PENDING.value,
                            SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value,
                        )
                    ),
                    or_(
                        SecurityAlert.next_retry_at.is_(None),
                        SecurityAlert.next_retry_at <= observed_at,
                    ),
                )
                .order_by(SecurityAlert.created_at.asc(), SecurityAlert.id.asc())
                .limit(SCHEDULER_SCAN_LIMIT)
            )
        )
        alert_resource_keys = [f"security-alert:{alert.id}" for alert in due_alerts]
        scheduled_alert_keys: set[str] = set()
        if alert_resource_keys:
            scheduled_alert_keys = set(
                db.scalars(
                    select(MaintenanceJob.resource_key).where(
                        MaintenanceJob.job_type
                        == MaintenanceJobType.SECURITY_ALERT_DELIVERY.value,
                        MaintenanceJob.resource_key.in_(alert_resource_keys),
                    )
                )
            )
        alert_added = 0
        for alert in due_alerts:
            resource_key = f"security-alert:{alert.id}"
            if resource_key in scheduled_alert_keys:
                existing += 1
                continue
            created = _enqueue(
                db,
                job_type=MaintenanceJobType.SECURITY_ALERT_DELIVERY,
                dedupe_key=f"security-alert:{alert.id}",
                resource_key=resource_key,
                payload={"alert_id": str(alert.id)},
                max_attempts=10,
                next_attempt_at=alert.next_retry_at or observed_at,
            )
            enqueued += int(created)
            existing += int(not created)
            if created:
                alert_added += 1
                scheduled_alert_keys.add(resource_key)
                if alert_added >= SCHEDULER_CATEGORY_LIMIT:
                    break

        expired_exports = list(
            db.scalars(
                select(UserExportJob)
                .where(
                    UserExportJob.status == UserExportStatus.COMPLETED.value,
                    UserExportJob.expires_at.is_not(None),
                    UserExportJob.expires_at <= observed_at,
                )
                .order_by(UserExportJob.expires_at.asc(), UserExportJob.id.asc())
                .limit(SCHEDULER_CATEGORY_LIMIT)
            )
        )
        for export_job in expired_exports:
            created = _enqueue(
                db,
                job_type=MaintenanceJobType.EXPORT,
                dedupe_key=f"export-cleanup:{export_job.id}:{export_job.revision}",
                owner_user_id=export_job.owner_user_id,
                resource_key=f"user-export:{export_job.id}",
                payload={
                    "action": "CLEANUP",
                    "export_job_id": str(export_job.id),
                },
                max_attempts=EXPORT_MAX_ATTEMPTS,
                next_attempt_at=observed_at,
            )
            enqueued += int(created)
            existing += int(not created)

        analytics_key = (
            f"analytics-retention:{observed_at.date().isoformat()}:"
            f"{settings.analytics_retrieval_retention_days}:"
            f"{settings.analytics_active_day_retention_days}"
        )
        created = _enqueue(
            db,
            job_type=MaintenanceJobType.ANALYTICS_RETENTION,
            dedupe_key=analytics_key,
            resource_key=f"analytics-retention:{observed_at.date().isoformat()}",
            payload={
                "retrieval_days": settings.analytics_retrieval_retention_days,
                "active_day_days": settings.analytics_active_day_retention_days,
            },
            max_attempts=ANALYTICS_MAX_ATTEMPTS,
            next_attempt_at=observed_at,
        )
        enqueued += int(created)
        existing += int(not created)

        hour_key = observed_at.strftime("%Y%m%d%H")
        owner_union = union(
            select(LocationPoint.user_id.label("user_id")),
            select(LocationDerivationState.user_id.label("user_id")),
        ).subquery()
        already_scheduled = select(MaintenanceJob.owner_user_id).where(
            MaintenanceJob.job_type == MaintenanceJobType.LOCATION_RETENTION.value,
            MaintenanceJob.dedupe_key.like(f"location-retention:{hour_key}:%"),
        )
        location_owners = list(
            db.scalars(
                select(owner_union.c.user_id)
                .where(
                    owner_union.c.user_id.not_in(already_scheduled),
                    owner_union.c.user_id.not_in(active_account_users),
                    owner_union.c.user_id.not_in(active_data_users),
                )
                .order_by(owner_union.c.user_id.asc())
                .limit(SCHEDULER_CATEGORY_LIMIT)
            )
        )
        for owner_user_id in location_owners:
            created = _enqueue(
                db,
                job_type=MaintenanceJobType.LOCATION_RETENTION,
                dedupe_key=f"location-retention:{hour_key}:{owner_user_id}",
                owner_user_id=owner_user_id,
                resource_key=f"location-owner:{owner_user_id}",
                payload={},
                max_attempts=5,
                next_attempt_at=observed_at,
            )
            enqueued += int(created)
            existing += int(not created)

        db.commit()

    return SchedulerResult(enqueued=enqueued, existing=existing)
