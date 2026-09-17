from uuid import uuid4

from sqlalchemy import func, select

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
from app.services.media_service import create_voice_memory


class BoundaryStorage:
    def __init__(self, db, audio: bytes):
        self.db = db
        self.audio = audio
        self.checked = False

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        del object_key, max_bytes
        # [人工注释][S1-PR18-FIX-001][S1-007] 对象下载本身也属于外部 I/O；
        # claim commit 后 Session 必须已经没有活跃事务/连接。
        assert self.db.in_transaction() is False
        self.checked = True
        return self.audio


class BoundaryASR:
    def __init__(self, db):
        self.db = db
        self.checked = False

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
        # [人工注释][S1-PR18-FIX-001][S1-007] 直接断言 provider 执行时没有
        # SQLAlchemy autobegin 留下的 transaction，防止回归成“无行锁但占连接”。
        assert self.db.in_transaction() is False
        self.checked = True
        return ASRResult(
            text="事务边界测试语音",
            confidence=0.95,
            provider="boundary-fake",
            model="boundary-v1",
        )


def test_voice_external_io_runs_outside_database_transaction():
    audio = b"ID3" + (b"\x11" * 64)
    user_id = uuid4()
    media_id = uuid4()

    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="voice-boundary"))
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
                storage_etag="boundary-etag",
            )
        )
        db.commit()

        storage = BoundaryStorage(db, audio)
        asr = BoundaryASR(db)
        asset, memory = create_voice_memory(
            db,
            user_id,
            media_id,
            VoiceMemoryCreate(),
            storage,
            asr,
        )

        assert asset.id == media_id
        assert memory.content == "事务边界测试语音"
        assert storage.checked is True
        assert asr.checked is True
        assert db.in_transaction() is False

        assert db.scalar(
            select(func.count(MediaASRClaim.media_id)).where(
                MediaASRClaim.media_id == media_id
            )
        ) == 0
        assert db.scalar(
            select(func.count(MediaEvidenceLink.id)).where(
                MediaEvidenceLink.media_id == media_id
            )
        ) == 1
        assert db.scalar(
            select(func.count(MemorySource.id)).where(
                MemorySource.source_type == SourceType.USER_VOICE,
                MemorySource.source_id == str(media_id),
            )
        ) == 1
        assert db.scalar(select(func.count(Memory.id)).where(Memory.id == memory.id)) == 1
