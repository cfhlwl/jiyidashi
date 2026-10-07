from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthProvider, AuthSession
from app.models import User
from app.services.auth_identity_service import canonicalize_phone_subject


@dataclass(frozen=True)
class AuthIdentityInventory:
    """Expected rollout inventory that is not schema corruption by itself."""

    unverified_email_identity_count: int
    phone_projection_without_identity_count: int
    dev_token_only_user_count: int
    active_account_deletion_count: int
    auth_disabled_user_count: int


@dataclass(frozen=True)
class AuthIdentityBlockingViolations:
    """Rows that block declaring the canonical identity foundation clean."""

    orphan_identity_count: int
    email_subject_mismatch_count: int
    duplicate_normalized_email_group_count: int
    multiple_email_identity_user_count: int
    multiple_phone_identity_user_count: int
    phone_projection_mismatch_count: int
    phone_normalization_conflict_count: int
    unverified_external_identity_count: int
    orphan_session_count: int

    @property
    def is_clean(self) -> bool:
        return not any(self.__dict__.values())


@dataclass(frozen=True)
class AuthIdentityPreflightReport:
    inventory: AuthIdentityInventory
    blocking: AuthIdentityBlockingViolations

    @property
    def is_clean(self) -> bool:
        return self.blocking.is_clean

    # Compatibility accessors keep existing operator/test reports readable while
    # making the inventory-vs-blocker split explicit above.
    @property
    def orphan_identity_count(self) -> int:
        return self.blocking.orphan_identity_count

    @property
    def email_subject_mismatch_count(self) -> int:
        return self.blocking.email_subject_mismatch_count

    @property
    def duplicate_normalized_email_group_count(self) -> int:
        return self.blocking.duplicate_normalized_email_group_count

    @property
    def multiple_email_identity_user_count(self) -> int:
        return self.blocking.multiple_email_identity_user_count

    @property
    def multiple_phone_identity_user_count(self) -> int:
        return self.blocking.multiple_phone_identity_user_count

    @property
    def phone_projection_mismatch_count(self) -> int:
        return self.blocking.phone_projection_mismatch_count

    @property
    def phone_normalization_conflict_count(self) -> int:
        return self.blocking.phone_normalization_conflict_count

    @property
    def unverified_identity_count(self) -> int:
        return (
            self.inventory.unverified_email_identity_count
            + self.blocking.unverified_external_identity_count
        )

    @property
    def dev_token_only_user_count(self) -> int:
        return self.inventory.dev_token_only_user_count

    @property
    def active_account_deletion_count(self) -> int:
        return self.inventory.active_account_deletion_count

    @property
    def auth_disabled_user_count(self) -> int:
        return self.inventory.auth_disabled_user_count

    @property
    def phone_projection_without_identity_count(self) -> int:
        return self.inventory.phone_projection_without_identity_count

    @property
    def orphan_session_count(self) -> int:
        return self.blocking.orphan_session_count


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


def run_auth_identity_preflight(db: Session) -> AuthIdentityPreflightReport:
    """Run read-only inventory and blocking checks without repair or auto-upgrade."""

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
    multiple_phone_users = _count(
        db,
        select(func.count())
        .select_from(
            select(AuthIdentity.user_id)
            .where(AuthIdentity.provider == AuthProvider.PHONE)
            .group_by(AuthIdentity.user_id)
            .having(func.count(AuthIdentity.id) > 1)
            .subquery()
        ),
    )

    phone_rows = list(
        db.execute(
            select(User.id, User.phone, AuthIdentity.subject)
            .outerjoin(
                AuthIdentity,
                (AuthIdentity.user_id == User.id)
                & (AuthIdentity.provider == AuthProvider.PHONE),
            )
            .where(or_(User.phone.is_not(None), AuthIdentity.id.is_not(None)))
        ).all()
    )
    phone_projection_mismatch = 0
    projection_without_identity = 0
    normalized_phones: dict[str, int] = {}
    for _user_id, projected_phone, identity_subject in phone_rows:
        if projected_phone is not None:
            try:
                canonical_projected = canonicalize_phone_subject(projected_phone)
                normalized_phones[canonical_projected] = (
                    normalized_phones.get(canonical_projected, 0) + 1
                )
            except Exception:
                phone_projection_mismatch += 1
        if projected_phone is not None and identity_subject is None:
            # Explicitly legacy/profile-only inventory. This is never auto-upgraded.
            projection_without_identity += 1
        elif identity_subject is not None:
            try:
                canonical_identity = canonicalize_phone_subject(identity_subject)
            except Exception:
                phone_projection_mismatch += 1
            else:
                if projected_phone != canonical_identity:
                    phone_projection_mismatch += 1

    phone_conflicts = sum(count - 1 for count in normalized_phones.values() if count > 1)

    return AuthIdentityPreflightReport(
        inventory=AuthIdentityInventory(
            unverified_email_identity_count=_count(
                db,
                select(func.count(AuthIdentity.id)).where(
                    AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
                    AuthIdentity.verified_at.is_(None),
                ),
            ),
            phone_projection_without_identity_count=projection_without_identity,
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
        ),
        blocking=AuthIdentityBlockingViolations(
            orphan_identity_count=orphan_identities,
            email_subject_mismatch_count=email_subject_mismatch,
            duplicate_normalized_email_group_count=duplicate_email_groups,
            multiple_email_identity_user_count=multiple_email_users,
            multiple_phone_identity_user_count=multiple_phone_users,
            phone_projection_mismatch_count=phone_projection_mismatch,
            phone_normalization_conflict_count=phone_conflicts,
            unverified_external_identity_count=_count(
                db,
                select(func.count(AuthIdentity.id)).where(
                    AuthIdentity.provider != AuthProvider.EMAIL_PASSWORD,
                    AuthIdentity.verified_at.is_(None),
                ),
            ),
            orphan_session_count=_count(
                db,
                select(func.count(AuthSession.id))
                .select_from(AuthSession)
                .outerjoin(User, User.id == AuthSession.user_id)
                .where(User.id.is_(None)),
            ),
        ),
    )


def assert_auth_identity_preflight_clean(db: Session) -> AuthIdentityPreflightReport:
    report = run_auth_identity_preflight(db)
    if not report.is_clean:
        raise RuntimeError("AUTH_IDENTITY_PREFLIGHT_NOT_CLEAN")
    return report
