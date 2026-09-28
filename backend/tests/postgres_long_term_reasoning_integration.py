"""Real PostgreSQL provider-gap invariants for V2-007 long-term reasoning."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Thread
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventKind, LifeEventMemoryLink
from app.life_event_schemas import LifeEventPatch
from app.life_stage_models import LifeStage, LifeStageEventLink, LifeStageKind
from app.life_stage_schemas import LifeStagePatch
from app.long_term_reasoning_models import LongTermReasoningStatus
from app.models import Memory, MemorySource, SourceType, User
from app.schemas import MemoryUpdate
from app.services.ai_gateway import AIGateway, AIInferenceRequest, AIProviderResult
from app.services.life_event_service import (
    create_life_event_memory_link,
    delete_life_event,
    delete_life_event_memory_link,
    patch_life_event,
)
from app.services.life_stage_service import (
    create_life_stage_event_link,
    delete_life_stage,
    delete_life_stage_event_link,
    patch_life_stage,
)
from app.services.long_term_reasoning_service import reason_about_life_stage
from app.services.memory_edit_service import edit_memory
from app.services.memory_service import get_memory_for_user, soft_delete_memory


def _settings() -> Settings:
    return Settings(
        app_env="test",
        ai_provider="disabled",
        ai_model="test-model",
        ai_max_output_tokens=2048,
    )


class _BlockingProvider:
    def __init__(self, caller_db):
        self.entered = Event()
        self.release = Event()
        self.caller_db = caller_db
        self.requests: list[AIInferenceRequest] = []

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self.requests.append(request)
        assert self.caller_db.in_transaction() is False
        self.entered.set()
        released = await asyncio.to_thread(self.release.wait, 20)
        assert released
        return AIProviderResult(
            output_text='{"answer":"旧答案","citations":["E1"]}',
            provider="blocking-pg",
            model="fixture",
            provider_request_id="blocking-request",
        )

    async def infer_image(self, request):
        del request
        raise AssertionError("V2-007 must not call image inference")


def _seed_owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"v2-007-{label}"))
        db.commit()
    return user_id


def _seed_stage(user_id: UUID, suffix: str) -> UUID:
    stage_id = uuid4()
    with SessionLocal() as db:
        db.add(
            LifeStage(
                id=stage_id,
                user_id=user_id,
                stage_kind=LifeStageKind.WORK,
                title=f"stage-{suffix}",
                started_at=datetime(2024, 1, 1, tzinfo=UTC),
                revision=0,
            )
        )
        db.commit()
    return stage_id


def _seed_event(user_id: UUID, suffix: str) -> UUID:
    event_id = uuid4()
    with SessionLocal() as db:
        db.add(
            LifeEvent(
                id=event_id,
                user_id=user_id,
                event_kind=LifeEventKind.WORK,
                title=f"event-{suffix}",
                started_at=datetime(2024, 2, 1, tzinfo=UTC),
                revision=0,
            )
        )
        db.commit()
    return event_id


def _link_stage_event(user_id: UUID, stage_id: UUID, event_id: UUID) -> None:
    with SessionLocal() as db:
        db.add(
            LifeStageEventLink(
                id=uuid4(),
                user_id=user_id,
                life_stage_id=stage_id,
                life_event_id=event_id,
            )
        )
        db.commit()


def _seed_trusted_memory(user_id: UUID, suffix: str) -> UUID:
    memory_id = uuid4()
    with SessionLocal() as db:
        memory = Memory(
            id=memory_id,
            user_id=user_id,
            content=f"trusted-memory-{suffix}",
            occurred_at=datetime(2024, 2, 2, tzinfo=UTC),
            source_type=SourceType.USER_TEXT,
            confidence=1.0,
            is_confirmed=True,
            is_deleted=False,
            edit_revision=0,
        )
        db.add(memory)
        db.commit()
        db.add(
            MemorySource(
                id=uuid4(),
                memory_id=memory_id,
                source_type=SourceType.USER_TEXT,
                raw_text=memory.content,
                confidence=1.0,
            )
        )
        db.commit()
    return memory_id


def _link_event_memory(user_id: UUID, event_id: UUID, memory_id: UUID) -> None:
    with SessionLocal() as db:
        db.add(
            LifeEventMemoryLink(
                id=uuid4(),
                user_id=user_id,
                life_event_id=event_id,
                memory_id=memory_id,
            )
        )
        db.commit()


def _run_gap_race(
    *,
    user_id: UUID,
    stage_id: UUID,
    mutate: Callable[[], None],
) -> None:
    with SessionLocal() as caller:
        provider = _BlockingProvider(caller)
        mutation_errors: list[BaseException] = []

        def mutation_worker() -> None:
            try:
                assert provider.entered.wait(timeout=20)
                mutate()
            except BaseException as exc:  # noqa: BLE001
                mutation_errors.append(exc)
            finally:
                provider.release.set()

        thread = Thread(target=mutation_worker)
        thread.start()
        result = asyncio.run(
            reason_about_life_stage(
                caller,
                user_id=user_id,
                life_stage_id=stage_id,
                question="这个阶段发生了什么？",
                ai_gateway=AIGateway(_settings(), provider),
            )
        )
        thread.join(timeout=20)
        assert not thread.is_alive()
        if mutation_errors:
            raise mutation_errors[0]

        assert len(provider.requests) == 1
        assert result.status == LongTermReasoningStatus.EVIDENCE_CHANGED_DURING_GENERATION
        assert result.answer is None
        assert result.citations == ()


def _stage_patch_race() -> UUID:
    owner = _seed_owner("stage-patch")
    stage_id = _seed_stage(owner, "stage-patch")

    def mutate() -> None:
        with SessionLocal() as db:
            patch_life_stage(
                db,
                user_id=owner,
                life_stage_id=stage_id,
                payload=LifeStagePatch(expected_revision=0, title="patched-stage"),
            )

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _stage_delete_race() -> UUID:
    owner = _seed_owner("stage-delete")
    stage_id = _seed_stage(owner, "stage-delete")

    def mutate() -> None:
        with SessionLocal() as db:
            delete_life_stage(db, user_id=owner, life_stage_id=stage_id)

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _event_patch_race() -> UUID:
    owner = _seed_owner("event-patch")
    stage_id = _seed_stage(owner, "event-patch")
    event_id = _seed_event(owner, "event-patch")
    _link_stage_event(owner, stage_id, event_id)

    def mutate() -> None:
        with SessionLocal() as db:
            patch_life_event(
                db,
                user_id=owner,
                life_event_id=event_id,
                payload=LifeEventPatch(expected_revision=0, title="patched-event"),
            )

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _event_delete_race() -> UUID:
    owner = _seed_owner("event-delete")
    stage_id = _seed_stage(owner, "event-delete")
    event_id = _seed_event(owner, "event-delete")
    _link_stage_event(owner, stage_id, event_id)

    def mutate() -> None:
        with SessionLocal() as db:
            delete_life_event(db, user_id=owner, life_event_id=event_id)

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _stage_event_unlink_race() -> UUID:
    owner = _seed_owner("stage-event-unlink")
    stage_id = _seed_stage(owner, "stage-event-unlink")
    event_id = _seed_event(owner, "stage-event-unlink")
    _link_stage_event(owner, stage_id, event_id)

    def mutate() -> None:
        with SessionLocal() as db:
            delete_life_stage_event_link(
                db,
                user_id=owner,
                life_stage_id=stage_id,
                life_event_id=event_id,
            )

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _memory_edit_race() -> UUID:
    owner = _seed_owner("memory-edit")
    stage_id = _seed_stage(owner, "memory-edit")
    event_id = _seed_event(owner, "memory-edit")
    memory_id = _seed_trusted_memory(owner, "memory-edit")
    _link_stage_event(owner, stage_id, event_id)
    _link_event_memory(owner, event_id, memory_id)

    def mutate() -> None:
        with SessionLocal() as db:
            edited = edit_memory(
                db,
                user_id=owner,
                memory_id=memory_id,
                payload=MemoryUpdate(
                    expected_revision=0,
                    content="edited-during-provider-gap",
                ),
            )
            assert edited is not None
            db.commit()

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _memory_delete_race() -> UUID:
    owner = _seed_owner("memory-delete")
    stage_id = _seed_stage(owner, "memory-delete")
    event_id = _seed_event(owner, "memory-delete")
    memory_id = _seed_trusted_memory(owner, "memory-delete")
    _link_stage_event(owner, stage_id, event_id)
    _link_event_memory(owner, event_id, memory_id)

    def mutate() -> None:
        with SessionLocal() as db:
            memory = get_memory_for_user(db, owner, memory_id, for_update=True)
            assert memory is not None
            soft_delete_memory(db, memory)
            db.commit()

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _event_memory_unlink_race() -> UUID:
    owner = _seed_owner("event-memory-unlink")
    stage_id = _seed_stage(owner, "event-memory-unlink")
    event_id = _seed_event(owner, "event-memory-unlink")
    memory_id = _seed_trusted_memory(owner, "event-memory-unlink")
    _link_stage_event(owner, stage_id, event_id)
    _link_event_memory(owner, event_id, memory_id)

    def mutate() -> None:
        with SessionLocal() as db:
            delete_life_event_memory_link(
                db,
                user_id=owner,
                life_event_id=event_id,
                memory_id=memory_id,
            )

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _new_event_evidence_race() -> UUID:
    owner = _seed_owner("new-event")
    stage_id = _seed_stage(owner, "new-event")
    event_id = _seed_event(owner, "new-event")

    def mutate() -> None:
        with SessionLocal() as db:
            create_life_stage_event_link(
                db,
                user_id=owner,
                life_stage_id=stage_id,
                life_event_id=event_id,
            )

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def _new_memory_evidence_race() -> UUID:
    owner = _seed_owner("new-memory")
    stage_id = _seed_stage(owner, "new-memory")
    event_id = _seed_event(owner, "new-memory")
    memory_id = _seed_trusted_memory(owner, "new-memory")
    _link_stage_event(owner, stage_id, event_id)

    def mutate() -> None:
        with SessionLocal() as db:
            create_life_event_memory_link(
                db,
                user_id=owner,
                life_event_id=event_id,
                memory_id=memory_id,
            )

    _run_gap_race(user_id=owner, stage_id=stage_id, mutate=mutate)
    return owner


def main() -> None:
    owners = [
        _stage_patch_race(),
        _stage_delete_race(),
        _event_patch_race(),
        _event_delete_race(),
        _stage_event_unlink_race(),
        _memory_edit_race(),
        _memory_delete_race(),
        _event_memory_unlink_race(),
        _new_event_evidence_race(),
        _new_memory_evidence_race(),
    ]

    with SessionLocal() as cleanup:
        for owner in owners:
            user = cleanup.get(User, owner)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()

    # The script deliberately has no persistence assertion for generated answers because
    # V2-007 has no answer table/cache authority to inspect.
    assert len(owners) == 10
    print("PostgreSQL Long-term Reasoning V2-007 provider-gap invariants PASS")


if __name__ == "__main__":
    main()
