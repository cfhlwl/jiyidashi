from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PrivacyState


def is_pause_active(paused_until: datetime | None) -> bool:
    if paused_until is None:
        return False
    if paused_until.tzinfo is None:
        paused_until = paused_until.replace(tzinfo=UTC)
    return paused_until > datetime.now(UTC)


def get_privacy_state(db: Session, user_id: UUID) -> PrivacyState:
    state = db.scalar(select(PrivacyState).where(PrivacyState.user_id == user_id))
    if state is None:
        state = PrivacyState(user_id=user_id)
        db.add(state)
        db.flush()
    return state
