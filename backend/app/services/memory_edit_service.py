from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory, MemoryEdit, MemorySource, MemoryType, SourceType
from app.schemas import MemoryUpdate
from app.services.embedding_service import invalidate_memory_embedding


class MemoryEditUnsupported(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class MemoryEditConflict(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def edit_memory(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
    payload: MemoryUpdate,
) -> Memory | None:
    # 同一 Memory 的 revision 必须串行递增；PostgreSQL 行锁避免并发编辑
    # 从同一旧快照各自生成相同 revision。
    memory = db.scalar(
        select(Memory)
        .where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if memory is None:
        return None

    # ObjectLocation 的真实当前位置由结构化 location_text/status 管理。
    # 只改 backing Memory 会制造两个互相矛盾的事实源，因此 Stage 1 通用编辑拒绝它。
    if memory.memory_type == MemoryType.OBJECT_LOCATION:
        raise MemoryEditUnsupported("OBJECT_LOCATION_EDIT_REQUIRES_STRUCTURED_FLOW")

    fields = payload.model_fields_set
    previous_title = memory.title
    previous_content = memory.content

    new_title = previous_title
    if "title" in fields:
        normalized_title = (payload.title or "").strip()
        new_title = normalized_title or None

    new_content = previous_content
    if "content" in fields:
        assert payload.content is not None
        new_content = payload.content.strip()

    changed_title = new_title != previous_title
    changed_content = new_content != previous_content
    if not changed_title and not changed_content:
        # response-loss 后相同 PATCH 重试命中 no-op，不重复制造 revision/source；
        # 即使 expected_revision 已落后，也可安全返回当前已提交结果。
        return memory

    if payload.expected_revision != memory.edit_revision:
        # 行锁保证两个不同内容的并发编辑不能从同一 base revision 都成功。
        raise MemoryEditConflict("MEMORY_EDIT_REVISION_CONFLICT")

    now = datetime.now(UTC)
    edit_id = uuid4()
    edit_source: MemorySource | None = None
    if changed_content:
        edit_source = MemorySource(
            id=uuid4(),
            memory_id=memory.id,
            source_type=SourceType.USER_TEXT,
            source_id=f"memory-edit:{edit_id}",
            raw_text=new_content,
            confidence=1.0,
            created_at=now,
        )
        db.add(edit_source)
        db.flush()

    revision = memory.edit_revision + 1
    db.add(
        MemoryEdit(
            id=edit_id,
            memory_id=memory.id,
            user_id=user_id,
            revision=revision,
            previous_title=previous_title,
            previous_content=previous_content,
            new_title=new_title,
            new_content=new_content,
            changed_title=changed_title,
            changed_content=changed_content,
            memory_source_id=None if edit_source is None else edit_source.id,
            created_at=now,
        )
    )

    memory.title = new_title
    memory.content = new_content
    memory.edit_revision = revision
    memory.edited_at = now
    # S3-009 vectors are derived from title/content/revision. Delete the old row in
    # this same trusted edit transaction so it cannot remain current after commit.
    invalidate_memory_embedding(db, memory.id)
    if changed_content:
        # 这是服务端根据“用户明确改写正文”派生的当前来源，不是客户端写 trust 字段。
        # 原照片/语音/AI 来源仍完整留在旧 MemorySource，当前文本则由新的 USER_TEXT source 证明。
        memory.source_type = SourceType.USER_TEXT
        memory.confidence = 1.0
        memory.is_confirmed = True
    db.flush()
    return memory
