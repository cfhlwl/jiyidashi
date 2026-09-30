from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.deps import AuthenticatedClaims
from app.models import User
from app.schemas import (
    AuthAcceptedResponse,
    AuthSessionRead,
    ChangePasswordRequest,
    DevTokenRequest,
    EmailResendRequest,
    EmailVerificationRequest,
    EmailVerificationResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegistrationResponse,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services.auth_recovery_service import (
    AuthRecoveryError,
    change_password,
    deliver_registration_verification,
    request_password_reset,
    resend_email_verification,
    reset_password,
    verify_email_token,
)
from app.services.auth_service import (
    authenticate_email_password,
    lock_login_for_token_issue,
    register_email_password,
)
from app.services.auth_session_service import (
    PublicAuthError,
    PublicSessionTokens,
    create_public_session,
    list_active_sessions,
    refresh_public_session,
    revoke_all_sessions,
    revoke_session,
)
from app.services.entitlement_service import create_legacy_full_entitlement

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db)]


def _client_ip(request: Request) -> str:
    # Only trust the peer address parsed by ASGI at this boundary.
    return request.client.host if request.client is not None else "unknown"


def _raise_auth_error(exc: PublicAuthError | AuthRecoveryError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _token_response(
    pair: PublicSessionTokens,
    *,
    account_deletion_in_progress: bool = False,
) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        session_id=pair.session_id,
        user_id=pair.user_id,
        access_expires_at=pair.expires_at,
        refresh_expires_at=pair.refresh_expires_at,
        account_deletion_in_progress=account_deletion_in_progress,
    )


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: DbSession,
) -> RegistrationResponse:
    user = register_email_password(db, payload, client_ip=_client_ip(request))
    deliver_registration_verification(db, user_id=user.id)
    return RegistrationResponse(user_id=user.id)


@router.post("/verify-email", response_model=EmailVerificationResponse)
def verify_email(
    payload: EmailVerificationRequest,
    db: DbSession,
) -> EmailVerificationResponse:
    try:
        result = verify_email_token(db, token=payload.token)
        if result.already_verified:
            return EmailVerificationResponse(
                verified=True,
                already_verified=True,
                session=None,
            )
        pair = create_public_session(
            db,
            user_id=result.user_id,
            device_id=payload.device_id,
            client_platform=payload.client_platform,
            device_name=payload.device_name,
        )
        return EmailVerificationResponse(
            verified=True,
            already_verified=False,
            session=_token_response(pair),
        )
    except (PublicAuthError, AuthRecoveryError) as exc:
        _raise_auth_error(exc)


@router.post(
    "/resend-verification",
    response_model=AuthAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resend_verification(
    payload: EmailResendRequest,
    request: Request,
    db: DbSession,
) -> AuthAcceptedResponse:
    resend_email_verification(
        db,
        email=str(payload.email),
        client_ip=_client_ip(request),
    )
    return AuthAcceptedResponse()


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenResponse:
    user = authenticate_email_password(db, payload, client_ip=_client_ip(request))
    locked_user, account_deletion_in_progress = lock_login_for_token_issue(
        db,
        user.id,
    )
    try:
        pair = create_public_session(
            db,
            user_id=locked_user.id,
            device_id=payload.device_id,
            client_platform=payload.client_platform,
            device_name=payload.device_name,
        )
    except PublicAuthError as exc:
        _raise_auth_error(exc)
    return _token_response(
        pair,
        account_deletion_in_progress=account_deletion_in_progress,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    try:
        pair = refresh_public_session(db, refresh_token=payload.refresh_token)
    except PublicAuthError as exc:
        _raise_auth_error(exc)
    return _token_response(pair)


@router.post(
    "/logout",
    response_model=AuthAcceptedResponse,
)
def logout(
    claims: AuthenticatedClaims,
    db: DbSession,
) -> AuthAcceptedResponse:
    revoke_session(
        db,
        user_id=claims.user_id,
        session_id=claims.session_id,
        reason="LOGOUT",
    )
    return AuthAcceptedResponse()


@router.post(
    "/logout-all",
    response_model=AuthAcceptedResponse,
)
def logout_all(
    claims: AuthenticatedClaims,
    db: DbSession,
) -> AuthAcceptedResponse:
    revoke_all_sessions(db, user_id=claims.user_id, reason="LOGOUT_ALL")
    return AuthAcceptedResponse()


@router.get("/sessions", response_model=list[AuthSessionRead])
def sessions(
    claims: AuthenticatedClaims,
    db: DbSession,
) -> list[AuthSessionRead]:
    return [
        AuthSessionRead(
            id=row.id,
            device_id=row.device_id,
            client_platform=row.client_platform,
            device_name=row.device_name,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            current=row.id == claims.session_id,
        )
        for row in list_active_sessions(db, user_id=claims.user_id)
    ]


@router.delete(
    "/sessions/{session_id}",
    response_model=AuthAcceptedResponse,
)
def revoke_own_session(
    session_id: UUID,
    claims: AuthenticatedClaims,
    db: DbSession,
) -> AuthAcceptedResponse:
    if not revoke_session(
        db,
        user_id=claims.user_id,
        session_id=session_id,
        reason="USER_REVOKE",
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AUTH_SESSION_NOT_FOUND",
        )
    return AuthAcceptedResponse()


@router.post(
    "/forgot-password",
    response_model=AuthAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: DbSession,
) -> AuthAcceptedResponse:
    request_password_reset(
        db,
        email=str(payload.email),
        client_ip=_client_ip(request),
    )
    # Enumeration-safe regardless of whether the account exists or delivery succeeds.
    return AuthAcceptedResponse()


@router.post(
    "/reset-password",
    response_model=AuthAcceptedResponse,
)
def password_reset(
    payload: ResetPasswordRequest,
    request: Request,
    db: DbSession,
) -> AuthAcceptedResponse:
    try:
        reset_password(
            db,
            token=payload.token,
            new_password=payload.new_password,
            client_ip=_client_ip(request),
        )
    except AuthRecoveryError as exc:
        _raise_auth_error(exc)
    return AuthAcceptedResponse()


@router.post(
    "/change-password",
    response_model=AuthAcceptedResponse,
)
def password_change(
    payload: ChangePasswordRequest,
    claims: AuthenticatedClaims,
    db: DbSession,
) -> AuthAcceptedResponse:
    try:
        change_password(
            db,
            user_id=claims.user_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AuthRecoveryError as exc:
        _raise_auth_error(exc)
    return AuthAcceptedResponse()


@router.post("/dev-token", response_model=TokenResponse)
def dev_token(payload: DevTokenRequest, db: DbSession) -> TokenResponse:
    if settings.is_production or not settings.enable_dev_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NOT_FOUND",
        )

    user_id = payload.user_id or uuid4()
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, nickname=payload.nickname)
        db.add(user)
        db.flush()
        create_legacy_full_entitlement(db, user_id=user.id)
        db.commit()

    try:
        pair = create_public_session(
            db,
            user_id=user_id,
            device_id="dev-token",
            client_platform="development",
            device_name="development token",
        )
    except PublicAuthError as exc:
        _raise_auth_error(exc)
    return _token_response(pair)
