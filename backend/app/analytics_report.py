from __future__ import annotations

import argparse
import json
from datetime import date

from app.core.db import SessionLocal
from app.services.analytics_service import analytics_report_payload


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
        payload = analytics_report_payload(
            db,
            start_date=args.start_date,
            end_date=args.end_date,
        )

    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
