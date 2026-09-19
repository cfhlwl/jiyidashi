from __future__ import annotations

import argparse
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import LocationDerivationState, LocationPoint
from app.services.location_service import maintain_location_history


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include an explicit timezone offset")
    return parsed.astimezone(UTC)


def sweep_all_location_history(*, now: datetime | None = None) -> tuple[int, int]:
    effective_now = now or datetime.now(UTC)
    with SessionLocal() as discovery:
        owner_ids: set[UUID] = set(
            discovery.scalars(select(LocationPoint.user_id).distinct())
        )
        owner_ids.update(
            discovery.scalars(select(LocationDerivationState.user_id))
        )

    deleted = 0
    for user_id in sorted(owner_ids, key=str):
        # [人工注释][S2-014] 每个 owner 独立事务：单账号失败不会把已经完成的其他
        # owner sweep 回滚；调度器可安全重跑，因为 rebuild/retention 都是收敛型操作。
        with SessionLocal() as db:
            result = maintain_location_history(
                db,
                user_id=user_id,
                now=effective_now,
            )
            deleted += result.raw_deleted
    return len(owner_ids), deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Advance location derivation watermarks and delete expired raw GPS."
    )
    parser.add_argument(
        "--now",
        help="Optional ISO-8601 UTC/offset timestamp for controlled maintenance runs.",
    )
    args = parser.parse_args()
    owners, deleted = sweep_all_location_history(now=_parse_now(args.now))
    print(f"location retention sweep: owners={owners} raw_deleted={deleted}")


if __name__ == "__main__":
    main()
