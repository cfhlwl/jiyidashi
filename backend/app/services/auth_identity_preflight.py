from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthProvider, AuthSession
from app.models import User
from app.services.auth_identity_service import canonicalize_phone_subject


@dataclass(frozen=True)
class AuthIdentityPreflightReport:
    orphan_identity_count: int
    email_subject_mismatch_count: int
    duplicate_normalized_email_group_count: int
    multiple_email_identity_user_count: int
    phone_normalization_conflict_count: int
    unverified_identity_count: int
    dev_token_only_user_count: int
    active_account_deletion_count: int
    auth_disabled_user_count: int
    orphan_session_count: int

    @property
    def is_clean(self) -> bool:
        return not any(self.__dict__.values())


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


def run_auth_identity_preflight(db: Session) -> AuthIdentityPreflightReport:
    """Run the AUTH-01 inventory as read-only queries.

    This function deliberately has no repair path. Ambiguous rows must be quarantined
    and resolved by a separately approved migration rather than guessed here.
    """

    orphan_identities = _count(
        db,
        select(func.count(AuthIdentity.id))
        .select_from(AuthIdentity)
        .outerjoin(User, User.id == AuthIdentity.user_id)
        .where(User.id.is_(None)),
    )
    email_subject_mismatch = _count(
        db,
        select(func.count(AuthIdentity.id))
        .join(User, User.id == AuthIdentity.user_id)
        .where(
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
            or_(
                User.email.is_(None),
                func.lower(func.trim(User.email)) != AuthIdentity.subject,
            ),
        ),
    )
    duplicate_email_groups = _count(
        db,
        select(func.count())
        .select_from(
            select(func.lower(func.trim(User.email)).label("canonical"))
            .where(User.email.is_not(None))
            .group_by(func.lower(func.trim(User.email)))
            .having(func.count(User.id) > 1)
            .subquery()
        ),
    )
    multiple_email_users = _count(
        db,
        select(func.count())
        .select_from(
            select(AuthIdentity.user_id)
            .where(AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD)
            .group_by(AuthIdentity.user_id)
            .having(func.count(AuthIdentity.id) > 1)
            .subquery()
        ),
    )

    phone_values = list(db.scalars(select(User.phone).where(User.phone.is_not(None))))
    normalized_phones: dict[str, int] = {}
    phone_conflicts = 0
    for phone in phone_values:
        try:
            canonical = canonicalize_phone_subject(phone)
        except Exception:
            phone_conflicts += 1
            continue
        normalized_phones[canonical] = normalized_phones.get(canonical, 0) + 1
    phone_conflicts += sum(count - 1 for count in normalized_phones.values() if count > 1)

    return AuthIdentityPreflightReport(
        orphan_identity_count=orphan_identities,
        email_subject_mismatch_count=email_subject_mismatch,
        duplicate_normalized_email_group_count=duplicate_email_groups,
        multiple_email_identity_user_count=multiple_email_users,
        phone_normalization_conflict_count=phone_conflicts,
        unverified_identity_count=_count(
            db,
            select(func.count(AuthIdentity.id)).where(
                AuthIdentity.verified_at.is_(None)
            ),
        ),
        dev_token_only_user_count=_count(
            db,
            select(func.count(User.id))
            .outerjoin(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.id.is_(None)),
        ),
        active_account_deletion_count=_count(
            db,
            select(func.count(AccountDeletionOperation.id)),
        ),
        auth_disabled_user_count=_count(
            db,
            select(func.count(User.id)).where(User.auth_disabled_at.is_not(None)),
        ),
        orphan_session_count=_count(
            db,
            select(func.count(AuthSession.id))
            .select_from(AuthSession)
            .outerjoin(User, User.id == AuthSession.user_id)
            .where(User.id.is_(None)),
        ),
    )


def assert_auth_identity_preflight_clean(db: Session) -> AuthIdentityPreflightReport:
    report = run_auth_identity_preflight(db)
    if not report.is_clean:
        raise RuntimeError("AUTH_IDENTITY_PREFLIGHT_NOT_CLEAN")
    return report
