from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.core.db import engine
from app.core.observability import configure_observability_log_level
from app.services.security_alerting import retry_due_security_alerts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deliver due durable SEC-015 security alerts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        choices=range(1, 101),
        metavar="[1-100]",
        help="Maximum due alerts processed in one bounded invocation.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_observability_log_level(settings.observability_log_level)
    retry_due_security_alerts(engine, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
