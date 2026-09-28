"""Real PostgreSQL composition gate for V2-011 Life Memoir Foundation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.db import SessionLocal
from app.life_event_models import (
    LifeEvent,
    LifeEventKind,
    LifeEventMemoryLink,
)
from app.life_memoir_models import LifeMemoirChapterStatus
from app.life_stage_models import LifeStage, LifeStageEventLink, LifeStageKind
from app.life_stage_schemas import LifeStagePatch
from app.models import Memory, MemorySource, SourceType, User
from app.services.ai_gateway import (
    AIGateway,
    AIInferenceRequest,
    AIProviderResult,
)
from app.services.life_memoir_service import (
    build_life_memoir_chapter,
    list_life_memoir_stages,
)
from app.services.life_stage_service import delete_life_stage, patch_life_stage
from app.long_term_reasoning_models import LongTermReasoningStatus

BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        app_env="test",
        ai_provider="disabled",
        ai_model="test-model",
        ai_max_output_tokens=2048,
    )


def _owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.commit()
    return user_id


def _stage(
    user_id: UUID,
    *,
    started_at: datetime,
    title: str,
    stage_id: UUID | None = None,
) -> UUID:
    stage_id = stage_id or uuid4()
    with SessionLocal() as db:
        db.add(
            LifeStage(
                id=stage_id,
                user_id=user_id,
                stage_kind=LifeStageKind.WORK,
                title=title,
                started_at=started_at,
            )
        )
        db.commit()
    return stage_id


def _page(user_id: UUID, *, limit: int = 100, cursor: str | None = None):
    with SessionLocal() as db:
        return list_life_memoir_stages(
            db,
            user_id=user_id,
            limit=limit,
            cursor_value=cursor,
        )


def _index_current_state() -> None:
    owner = _owner("life-memoir-pg-owner")
    other = _owner("life-memoir-pg-other")
    first_id = UUID("11111111-1111-4111-8111-111111111111")
    second_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    other_id = uuid4()

    _stage(owner, stage_id=first_id, started_at=BASE, title="first")
    _stage(owner, stage_id=second_id, started_at=BASE, title="second")
    _stage(other, stage_id=other_id, started_at=BASE, title="private-other")

    first = _page(owner, limit=1)
    assert [item.life_stage_id for item in first.items] == [first_id]
    assert first.next_cursor is not None

    second = _page(owner, limit=1, cursor=first.next_cursor)
    assert [item.life_stage_id for item in second.items] == [second_id]
    assert second.next_cursor is None
    assert other_id not in {item.life_stage_id for item in first.items + second.items}
    assert "private-other" not in str(first.model_dump()) + str(second.model_dump())

    with SessionLocal() as db:
        patch_life_stage(
            db,
            user_id=owner,
            life_stage_id=second_id,
            payload=LifeStagePatch(
                expected_revision=0,
                started_at=BASE - timedelta(days=1),
            ),
        )
    reordered = _page(owner)
    assert [item.life_stage_id for item in reordered.items] == [second_id, first_id]

    with SessionLocal() as db:
        delete_life_stage(db, user_id=owner, life_stage_id=first_id)
    deleted = _page(owner)
    assert [item.life_stage_id for item in deleted.items] == [second_id]


def _reasoning_fixture(owner: UUID) -> tuple[UUID, UUID]:
    stage_id = uuid4()
    event_id = uuid4()
    memory_id = uuid4()
    source_id = uuid4()
    with SessionLocal() as db:
        db.add(
            LifeStage(
                id=stage_id,
                user_id=owner,
                stage_kind=LifeStageKind.WORK,
                title="memoir-stage",
                started_at=BASE,
            )
        )
        db.add(
            LifeEvent(
                id=event_id,
                user_id=owner,
                event_kind=LifeEventKind.WORK,
                title="memoir-event",
                started_at=BASE + timedelta(days=1),
            )
        )
        db.add(
            Memory(
                id=memory_id,
                user_id=owner,
                content="trusted memoir evidence",
                occurred_at=BASE + timedelta(days=1),
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
                is_confirmed=True,
            )
        )
        db.commit()

        db.add(
            MemorySource(
                id=source_id,
                memory_id=memory_id,
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
            )
        )
        db.add(
            LifeStageEventLink(
                user_id=owner,
                life_stage_id=stage_id,
                life_event_id=event_id,
            )
        )
        db.add(
            LifeEventMemoryLink(
                user_id=owner,
                life_event_id=event_id,
                memory_id=memory_id,
            )
        )
        db.commit()
    return stage_id, memory_id


class _BlockingProvider:
    def __init__(self):
        self.entered = Event()
        self.release = Event()
        self.requests: list[AIInferenceRequest] = []

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self.requests.append(request)
        self.entered.set()
        released = await asyncio.to_thread(self.release.wait, 20)
        assert released
        return AIProviderResult(
            output_text='{"answer":"old chapter","citations":["E1"]}',
            provider="life-memoir-pg",
            model="fixture",
            provider_request_id="memoir-pg-request",
        )

    async def infer_image(self, request):
        del request
        raise AssertionError("V2-011 must not call image inference")


async def _chapter_inherits_v2_007_stale_evidence() -> None:
    owner = _owner("life-memoir-pg-chapter")
    stage_id, memory_id = _reasoning_fixture(owner)
    provider = _BlockingProvider()
    gateway = AIGateway(_settings(), provider)

    async def run_chapter():
        with SessionLocal() as db:
            return await build_life_memoir_chapter(
                db,
                user_id=owner,
                life_stage_id=stage_id,
                ai_gateway=gateway,
            )

    task = asyncio.create_task(run_chapter())
    entered = await asyncio.to_thread(provider.entered.wait, 20)
    assert entered
    assert len(provider.requests) == 1

    with SessionLocal() as db:
        memory = db.get(Memory, memory_id)
        assert memory is not None
        memory.content = "mutated during provider io"
        memory.edit_revision += 1
        db.commit()

    provider.release.set()
    chapter = await task

    assert chapter.status == LifeMemoirChapterStatus.CHAPTER_PARTIAL
    assert (
        chapter.reasoning_status
        == LongTermReasoningStatus.EVIDENCE_CHANGED_DURING_GENERATION
    )
    assert chapter.narrative is None
    assert chapter.citations == []


async def main() -> None:
    _index_current_state()
    await _chapter_inherits_v2_007_stale_evidence()


if __name__ == "__main__":
    asyncio.run(main())
