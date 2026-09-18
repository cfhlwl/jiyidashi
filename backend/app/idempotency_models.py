from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ClientMutation(Base):
    __tablename__ = "client_mutations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "operation_type",
            "client_uuid",
            name="uq_client_mutations_user_operation_uuid",
        ),
    )

    # 幂等账本只保存客户端稳定操作键、请求指纹和最终业务资源 ID；
    # 它不保存 Memory 内容副本，也不参与 confidence / Evidence 等可信事实判定。
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    operation_type: Mapped[str] = mapped_column(String(80))
    client_uuid: Mapped[UUID] = mapped_column()
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
