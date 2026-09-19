from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class AccountDeletionOperation(Base):
    """Transient durable gate for one in-progress account deletion.

    [人工注释][S1-022] 这不是永久注销墓碑。它只在 User 仍存在、账号注销尚未最终提交时
    保留，用来跨对象存储等待/进程重启阻止新用户数据写入。最终删除 User 的事务会显式
    删除本行，因此完成注销后不长期保存账号身份关联记录。
    """

    __tablename__ = "account_deletion_operations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            name="uq_account_deletion_operations_user",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    # 首次发起的客户端 request_id 是本次 destructive intent 的 canonical id；
    # 后续不同 request_id 的重试也会 join 这一个 gate，避免客户端重启后被永久卡死。
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    # 若发起注销时已有 S1-021 正在进行，则复用它；否则保存服务端新生成的内部 UUID，
    # 绝不复用 Account Delete 的客户端 request_id，避免撞到历史 COMPLETED S1-021 receipt。
    data_deletion_request_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
