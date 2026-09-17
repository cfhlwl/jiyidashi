from __future__ import annotations

import threading
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.media_models import (
    MediaASRClaim,
    MediaAsset,
    MediaEvidenceLink,
    MediaKind,
    MediaStatus,
)
from app.models import Memory, MemorySource, SourceType, User
from app.schemas import VoiceMemoryCreate
from app.services.asr import ASRResult
from app.services.media_service import MediaError, create_voice_memory


class IntegrationStorage:
    def __init__(self, audio: bytes):
        self.audio = audio

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        del object_key
        assert len(self.audio) <= max_bytes
        return self.audio


class BlockingASR:
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()
        self.entered = threading.Event()
        self.release = threading.Event()

    def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> ASRResult:
        assert audio.startswith(b"ID3")
        assert content_type == "audio/mpeg"
        assert filename == "voice.mp3"
        with self._lock:
            self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError("test provider release timeout")
        return ASRResult(
            text="并发单飞测试语音",
            confidence=0.95,
            provider="postgres-fake",
            model="postgres-fake-v1",
        )


@dataclass
class WorkerResults:
    memory_ids: list[UUID] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_memory(self, memory_id: UUID) -> None:
        with self.lock:
            self.memory_ids.append(memory_id)

    def add_error(self, code: str) -> None:
        with self.lock:
            self.errors.append(code)


def _worker(
    *,
    user_id: UUID,
    media_id: UUID,
    storage: IntegrationStorage,
    asr: BlockingASR,
    results: WorkerResults,
) -> None:
    with SessionLocal() as db:
        try:
            _, memory = create_voice_memory(
                db,
                user_id,
                media_id,
                VoiceMemoryCreate(),
                storage,
                asr,
            )
        except MediaError as exc:
            results.add_error(exc.code)
            return
        results.add_memory(memory.id)


def main() -> None:
    # [人工注释][S1-PR18-FIX-002][S1-007] 该脚本只在 backend-ci 的真实 PostgreSQL
    # migration 后运行；两个独立 Session 并发同一 media，必须证明 provider side effect 也单飞。
    audio = b"ID3" + (b"\x33" * 128)
    user_id = uuid4()
    media_id = uuid4()
    storage = IntegrationStorage(audio)
    asr = BlockingASR()
    results = WorkerResults()

    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="postgres-voice-single-flight"))
        # [人工注释][S1-PR18-FIX-002] User 与 MediaAsset 没有 ORM relationship 可供
        # unit-of-work 推导插入顺序；真实 PostgreSQL fixture 先 flush owner，避免 FK setup 假失败。
        db.flush()
        db.add(
            MediaAsset(
                id=media_id,
                user_id=user_id,
                client_upload_id=uuid4(),
                kind=MediaKind.AUDIO,
                status=MediaStatus.READY,
                upload_object_key=f"media/_staging/{user_id}/{media_id}",
                object_key=f"media/{user_id}/{media_id}",
                content_type="audio/mpeg",
                size_bytes=len(audio),
                original_filename="voice.mp3",
                storage_etag="postgres-voice-etag",
            )
        )
        db.commit()

    first = threading.Thread(
        target=_worker,
        kwargs={
            "user_id": user_id,
            "media_id": media_id,
            "storage": storage,
            "asr": asr,
            "results": results,
        },
        daemon=True,
    )
    first.start()
    if not asr.entered.wait(timeout=10):
        raise AssertionError("first request never entered ASR provider")

    second = threading.Thread(
        target=_worker,
        kwargs={
            "user_id": user_id,
            "media_id": media_id,
            "storage": storage,
            "asr": asr,
            "results": results,
        },
        daemon=True,
    )
    second.start()
    second.join(timeout=10)
    if second.is_alive():
        raise AssertionError("second request blocked instead of observing ASR claim")

    asr.release.set()
    first.join(timeout=10)
    if first.is_alive():
        raise AssertionError("first request did not finalize")

    assert asr.calls == 1, f"expected one provider call, got {asr.calls}"
    assert results.errors == ["ASR_IN_PROGRESS"], results.errors
    assert len(results.memory_ids) == 1, results.memory_ids

    with SessionLocal() as db:
        source_count = db.scalar(
            select(func.count(MemorySource.id)).where(
                MemorySource.source_type == SourceType.USER_VOICE,
                MemorySource.source_id == str(media_id),
            )
        )
        link_count = db.scalar(
            select(func.count(MediaEvidenceLink.id)).where(
                MediaEvidenceLink.media_id == media_id
            )
        )
        claim_count = db.scalar(
            select(func.count(MediaASRClaim.media_id)).where(
                MediaASRClaim.media_id == media_id
            )
        )
        memory_count = db.scalar(
            select(func.count(Memory.id)).where(Memory.id.in_(results.memory_ids))
        )
        assert source_count == 1, source_count
        assert link_count == 1, link_count
        assert claim_count == 0, claim_count
        assert memory_count == 1, memory_count

        db.execute(delete(User).where(User.id == user_id))
        db.commit()

    print("PostgreSQL voice ASR single-flight PASS")


if __name__ == "__main__":
    main()
