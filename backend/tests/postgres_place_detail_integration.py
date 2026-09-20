from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.core.db import SessionLocal
from app.models import Place, User, Visit
from app.services.place_detail_service import get_place_detail

USER_ID=UUID("aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa")
PLACE_ID=UUID("bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb")
HIGH=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
LOW=UUID("11111111-1111-4111-8111-111111111111")


def main() -> None:
    tie=datetime(2026,9,20,10,0,tzinfo=UTC)
    with SessionLocal() as db:
        existing = db.get(User, USER_ID)
        if existing is not None:
            db.delete(existing)
            db.commit()
        db.add(User(id=USER_ID, nickname="place-detail-pg"))
        db.flush()
        db.add(Place(id=PLACE_ID,user_id=USER_ID,name="PG 地点",visit_count=2))
        db.flush()
        db.add_all([
            Visit(id=HIGH,user_id=USER_ID,place_id=PLACE_ID,arrived_at=tie,finalized_at=tie),
            Visit(id=LOW,user_id=USER_ID,place_id=PLACE_ID,arrived_at=tie),
        ])
        db.commit()

    with SessionLocal() as db:
        first=get_place_detail(db,user_id=USER_ID,place_id=PLACE_ID,limit=1,cursor_value=None)
        assert [v.id for v in first.visits]==[HIGH]
        assert first.next_cursor is not None
        second=get_place_detail(db,user_id=USER_ID,place_id=PLACE_ID,limit=1,cursor_value=first.next_cursor)
        assert [v.id for v in second.visits]==[LOW]
        assert second.next_cursor is None
        assert first.visits[0].visit_finalized is True
        assert second.visits[0].visit_finalized is False

    with SessionLocal() as db:
        user = db.get(User, USER_ID)
        assert user is not None
        db.delete(user)
        db.commit()
    print("PostgreSQL Place detail pagination PASS")


if __name__=="__main__":
    main()
