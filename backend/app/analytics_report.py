from __future__ import annotations

import argparse
import json
from datetime import date

from app.core.db import SessionLocal
from app.services.analytics_service import retrieval_aggregate, retention_aggregates


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate privacy-safe product analytics.")
    parser.add_argument("--from", dest="start_date", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end_date", type=_parse_date, required=True)
    args = parser.parse_args(argv)
    if args.end_date < args.start_date:
        parser.error("--to must be on or after --from")

    with SessionLocal() as db:
        retrieval = retrieval_aggregate(
            db,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        retention = retention_aggregates(
            db,
            start_date=args.start_date,
            end_date=args.end_date,
        )

    payload = {
        "from": args.start_date.isoformat(),
        "to": args.end_date.isoformat(),
        "retrieval": {
            "attempts": retrieval.attempts,
            "successes": retrieval.successes,
            "success_rate": retrieval.success_rate,
        },
        "retention": [
            {
                "cohort_day": item.cohort_day.isoformat(),
                "cohort_users": item.cohort_users,
                "eligible_d1": item.eligible_d1,
                "retained_d1": item.retained_d1,
                "d1_rate": item.d1_rate,
                "eligible_d7": item.eligible_d7,
                "retained_d7": item.retained_d7,
                "d7_rate": item.d7_rate,
                "eligible_d30": item.eligible_d30,
                "retained_d30": item.retained_d30,
                "d30_rate": item.d30_rate,
            }
            for item in retention
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
