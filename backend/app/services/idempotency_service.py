from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.idempotency_models import ClientMutation


@dataclass(frozen=True)
class IdempotencyConflict(Exception):
    detail: str


@dataclass(frozen=True)
class IdempotencyResourceGone(Exception):
    detail: str


def canonical_request_fingerprint(payload: dict) -> str:
    # 指纹只用于判断“同一个幂等键是否仍是同一业务请求”；
    # JSON 必须稳定排序，避免字典键顺序导致误判。
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _get_mutation(
    db: Session,
    user_id: UUID,
    operation_type: str,
    client_uuid: UUID,
) -> ClientMutation | None:
    return db.scalar(
        select(ClientMutation).where(
            ClientMutation.user_id == user_id,
            ClientMutation.operation_type == operation_type,
            ClientMutation.client_uuid == client_uuid,
        )
    )


def _load_existing_resource[T](
    db: Session,
    *,
    mutation: ClientMutation,
    fingerprint: str,
    resource_type: str,
    load_resource: Callable[[Session, UUID], T | None],
) -> T:
    if mutation.request_fingerprint != fingerprint:
        raise IdempotencyConflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST")
    if mutation.resource_type != resource_type:
        raise IdempotencyConflict("IDEMPOTENCY_RESOURCE_TYPE_MISMATCH")
    resource = load_resource(db, mutation.resource_id)
    if resource is None:
        # 已有幂等水位对应的资源如果后来被删除/失效，
        # 重试不得重新创建第二份业务事实；必须 fail closed。
        raise IdempotencyResourceGone("IDEMPOTENT_RESOURCE_GONE")
    return resource


def execute_idempotent_mutation[T](
    db: Session,
    *,
    user_id: UUID,
    operation_type: str,
    client_uuid: UUID | None,
    fingerprint_payload: dict,
    resource_type: str,
    create_resource: Callable[[Session], T],
    resource_id: Callable[[T], UUID],
    load_resource: Callable[[Session, UUID], T | None],
) -> T:
    """Create once, or return the authoritative resource for the same client key."""

    if client_uuid is None:
        resource = create_resource(db)
        db.commit()
        return resource

    fingerprint = canonical_request_fingerprint(fingerprint_payload)
    existing = _get_mutation(db, user_id, operation_type, client_uuid)
    if existing is not None:
        return _load_existing_resource(
            db,
            mutation=existing,
            fingerprint=fingerprint,
            resource_type=resource_type,
            load_resource=load_resource,
        )

    resource = create_resource(db)
    db.add(
        ClientMutation(
            user_id=user_id,
            operation_type=operation_type,
            client_uuid=client_uuid,
            request_fingerprint=fingerprint,
            resource_type=resource_type,
            resource_id=resource_id(resource),
        )
    )
    try:
        # 业务资源与幂等账本同一事务提交；
        # 并发请求若唯一键竞争失败，当前资源也会整体 rollback，不会留下重复 Memory/Evidence。
        db.commit()
        return resource
    except IntegrityError:
        db.rollback()
        existing = _get_mutation(db, user_id, operation_type, client_uuid)
        if existing is None:
            raise
        return _load_existing_resource(
            db,
            mutation=existing,
            fingerprint=fingerprint,
            resource_type=resource_type,
            load_resource=load_resource,
        )
