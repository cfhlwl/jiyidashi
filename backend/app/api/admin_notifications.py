from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin_deps import (
    AdminPrincipal,
    require_admin_mutation,
    require_admin_roles,
)
from app.admin_models import AdminRole
from app.core.db import get_db
from app.notification_models import NotificationCampaign, NotificationCampaignStatus
from app.notification_schemas import (
    AdminNotificationCampaignCancel,
    AdminNotificationCampaignCreate,
    AdminNotificationCampaignPreview,
    AdminNotificationCampaignRead,
    AdminNotificationCampaignSubmit,
)
from app.services.admin_security import AdminOperationError
from app.services.notification_service import (
    campaign_confirmation_token,
    cancel_notification_campaign,
    create_notification_campaign,
    eligible_device_counts,
    notification_campaign_projection,
    submit_notification_campaign,
)

router = APIRouter(prefix="/notifications", tags=["admin-notifications"])
DbSession = Annotated[Session, Depends(get_db)]
AnyAdminRead = Annotated[
    AdminPrincipal,
    Depends(
        require_admin_roles(
            AdminRole.SUPER_ADMIN,
            AdminRole.OPERATOR,
            AdminRole.SUPPORT_READONLY,
        )
    ),
]
OperatorMutation = Annotated[
    AdminPrincipal,
    Depends(
        require_admin_mutation(
            AdminRole.SUPER_ADMIN,
            AdminRole.OPERATOR,
        )
    ),
]


def _raise(exc: AdminOperationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.post(
    "/campaigns",
    response_model=AdminNotificationCampaignRead,
    status_code=201,
)
def create_campaign(
    payload: AdminNotificationCampaignCreate,
    db: DbSession,
    principal: OperatorMutation,
) -> AdminNotificationCampaignRead:
    try:
        campaign = create_notification_campaign(
            db,
            actor=principal.account,
            payload=payload,
        )
        return notification_campaign_projection(db, campaign_id=campaign.id)
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)


@router.get(
    "/campaigns/{campaign_id}/preview",
    response_model=AdminNotificationCampaignPreview,
)
def preview_campaign(
    campaign_id: UUID,
    db: DbSession,
    _: AnyAdminRead,
) -> AdminNotificationCampaignPreview:
    try:
        projection = notification_campaign_projection(db, campaign_id=campaign_id)
        if projection.status != NotificationCampaignStatus.DRAFT:
            raise AdminOperationError("NOTIFICATION_CAMPAIGN_NOT_DRAFT", 409)
        campaign = db.get(NotificationCampaign, campaign_id)
        assert campaign is not None
        return AdminNotificationCampaignPreview(
            campaign_id=campaign.id,
            revision=campaign.revision,
            eligible=eligible_device_counts(db, campaign=campaign),
            confirmation_token=campaign_confirmation_token(
                db,
                campaign=campaign,
            ),
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)


@router.post(
    "/campaigns/{campaign_id}/submit",
    response_model=AdminNotificationCampaignRead,
)
def submit_campaign(
    campaign_id: UUID,
    payload: AdminNotificationCampaignSubmit,
    db: DbSession,
    principal: OperatorMutation,
) -> AdminNotificationCampaignRead:
    try:
        campaign = submit_notification_campaign(
            db,
            actor=principal.account,
            campaign_id=campaign_id,
            payload=payload,
        )
        return notification_campaign_projection(db, campaign_id=campaign.id)
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)


@router.get(
    "/campaigns/{campaign_id}",
    response_model=AdminNotificationCampaignRead,
)
def read_campaign(
    campaign_id: UUID,
    db: DbSession,
    _: AnyAdminRead,
) -> AdminNotificationCampaignRead:
    try:
        return notification_campaign_projection(db, campaign_id=campaign_id)
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)


@router.post(
    "/campaigns/{campaign_id}/cancel",
    response_model=AdminNotificationCampaignRead,
)
def cancel_campaign(
    campaign_id: UUID,
    payload: AdminNotificationCampaignCancel,
    db: DbSession,
    principal: OperatorMutation,
) -> AdminNotificationCampaignRead:
    try:
        campaign = cancel_notification_campaign(
            db,
            actor=principal.account,
            campaign_id=campaign_id,
            expected_revision=payload.expected_revision,
        )
        return notification_campaign_projection(db, campaign_id=campaign.id)
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
