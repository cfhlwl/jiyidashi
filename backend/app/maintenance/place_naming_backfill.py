from __future__ import annotations

import argparse
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Place
from app.services.place_naming_service import backfill_automatic_place_names_for_user
from app.services.place_resolver import get_place_resolver


@dataclass(frozen=True)
class PlaceNamingSweepResult:
    owners: int
    attempted: int
    resolved: int
    provider_failures: int


@dataclass(frozen=True)
class PlaceNamingReadonlyInventory:
    provider: str
    key_configured: bool
    eligible_places: int
    eligible_owners: int


def read_only_place_naming_inventory() -> PlaceNamingReadonlyInventory:
    """Read-only provider/queue counts; never load, return or log secrets/coordinates."""
    settings = get_settings()
    criteria = (
        Place.user_name.is_(None),
        Place.automatic_name.is_(None),
        Place.latitude.is_not(None),
        Place.longitude.is_not(None),
    )
    with SessionLocal() as db:
        eligible_places = db.scalar(
            select(func.count(Place.id)).where(*criteria)
        ) or 0
        eligible_owners = db.scalar(
            select(func.count(func.distinct(Place.user_id))).where(*criteria)
        ) or 0
        # Even an accidental ORM dirty state must not be committed by inspection.
        db.rollback()
    return PlaceNamingReadonlyInventory(
        provider=settings.place_resolver_provider,
        key_configured=bool(settings.amap_web_service_key.strip()),
        eligible_places=int(eligible_places),
        eligible_owners=int(eligible_owners),
    )


def discover_unnamed_place_owner_ids(*, max_owners: int) -> list[UUID]:
    if max_owners < 1 or max_owners > 1000:
        raise ValueError("max_owners must be between 1 and 1000")
    with SessionLocal() as db:
        owners = list(
            db.scalars(
                select(Place.user_id)
                .where(
                    Place.user_name.is_(None),
                    Place.automatic_name.is_(None),
                    Place.latitude.is_not(None),
                    Place.longitude.is_not(None),
                )
                .distinct()
                .order_by(Place.user_id)
                .limit(max_owners)
            )
        )
        db.rollback()
    return owners


def sweep_unnamed_place_names(*, max_owners: int = 100) -> PlaceNamingSweepResult:
    settings = get_settings()
    if settings.place_resolver_provider == "disabled":
        return PlaceNamingSweepResult(
            owners=0,
            attempted=0,
            resolved=0,
            provider_failures=0,
        )

    resolver = get_place_resolver()
    attempted = 0
    resolved = 0
    provider_failures = 0
    owners = discover_unnamed_place_owner_ids(max_owners=max_owners)
    for owner_id in owners:
        # Each owner gets at most PLACE_NAMING_BACKFILL_BATCH_SIZE places per invocation.
        # Operators can re-run this idempotently; user_name precedence remains authoritative.
        result = backfill_automatic_place_names_for_user(
            owner_id,
            resolver=resolver,
            settings=settings,
        )
        attempted += result.attempted
        resolved += result.resolved
        provider_failures += result.provider_failures

    return PlaceNamingSweepResult(
        owners=len(owners),
        attempted=attempted,
        resolved=resolved,
        provider_failures=provider_failures,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bounded server-side backfill for existing unnamed Places."
    )
    parser.add_argument(
        "--max-owners",
        type=int,
        default=100,
        help="Maximum owners to process in this invocation (1..1000).",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="READ ONLY: inspect provider/key presence and anonymous eligible counts; no backfill.",
    )
    args = parser.parse_args()
    if args.status_only:
        try:
            result = read_only_place_naming_inventory()
        except Exception:
            # Pydantic/provider/DB errors can contain sensitive inputs. No raw exception.
            print("place naming inventory: CONFIG_OR_DATABASE_UNAVAILABLE")
            raise SystemExit(2) from None
        print(
            "place naming inventory: "
            f"provider={result.provider} "
            f"web_key_set={'YES' if result.key_configured else 'NO'} "
            f"eligible_places={result.eligible_places} "
            f"eligible_owners={result.eligible_owners} "
            "mutation=NONE"
        )
        return
    result = sweep_unnamed_place_names(max_owners=args.max_owners)
    print(
        "place naming backfill: "
        f"owners={result.owners} attempted={result.attempted} "
        f"resolved={result.resolved} provider_failures={result.provider_failures}"
    )


if __name__ == "__main__":
    main()
