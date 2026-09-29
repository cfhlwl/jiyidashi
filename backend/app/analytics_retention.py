from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.analytics_service import prune_analytics


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Prune raw product analytics.")
    parser.add_argument(
        "--retrieval-days",
        type=int,
        default=settings.analytics_retrieval_retention_days,
    )
    parser.add_argument(
        "--active-day-days",
        type=int,
        default=settings.analytics_active_day_retention_days,
    )
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        retrieval_deleted, active_deleted = prune_analytics(
            db,
            retrieval_days=args.retrieval_days,
            active_day_days=args.active_day_days,
        )
    print(
        f"retrieval_deleted={retrieval_deleted} active_day_deleted={active_deleted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
