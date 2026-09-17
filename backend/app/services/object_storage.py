from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings


# [人工注释][S1-006] 公共 API 永远只拿短时签名请求，不暴露永久公开 URL。
# COS/OSS/S3 兼容实现统一隔离在此抽象后。
@dataclass(frozen=True)
class PresignedTransfer:
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class StoredObject:
    size_bytes: int
    content_type: str
    etag: str | None


class ObjectStorageError(RuntimeError):
    pass


class ObjectNotFound(ObjectStorageError):
    pass


class ObjectStorage(Protocol):
    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer: ...

    def sign_download(self, object_key: str) -> PresignedTransfer: ...

    def stat_object(self, object_key: str) -> StoredObject: ...

    def read_prefix(self, object_key: str, max_bytes: int) -> bytes: ...

    def read_object(self, object_key: str, max_bytes: int) -> bytes: ...

    def promote_object(self, source_key: str, destination_key: str) -> None: ...

    def delete_object(self, object_key: str) -> None: ...


class DisabledObjectStorage:
    # [人工注释][S1-006] 未配置对象存储时媒体接口 fail closed，不能退化成本机公开目录。
    def _unavailable(self) -> None:
        raise ObjectStorageError("object storage is not configured")

    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer:
        self._unavailable()
        raise AssertionError("unreachable")

    def sign_download(self, object_key: str) -> PresignedTransfer:
        self._unavailable()
        raise AssertionError("unreachable")

    def stat_object(self, object_key: str) -> StoredObject:
        self._unavailable()
        raise AssertionError("unreachable")

    def read_prefix(self, object_key: str, max_bytes: int) -> bytes:
        self._unavailable()
        raise AssertionError("unreachable")

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        self._unavailable()
        raise AssertionError("unreachable")

    def promote_object(self, source_key: str, destination_key: str) -> None:
        self._unavailable()

    def delete_object(self, object_key: str) -> None:
        self._unavailable()


class S3ObjectStorage:
    # [人工注释][S1-006] 使用 S3 SigV4 兼容边界承载 COS/OSS 私有桶。
    # PUT 只写 staging；完成后由服务端 COPY 到 final，旧 PUT 签名不能覆盖 Evidence 对象。
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url or None,
            region_name=settings.storage_region or None,
            aws_access_key_id=settings.storage_access_key_id,
            aws_secret_access_key=settings.storage_secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.storage_addressing_style},
            ),
        )

    def _expiry(self) -> datetime:
        return datetime.now(UTC) + timedelta(
            seconds=self._settings.storage_presign_ttl_seconds
        )

    @staticmethod
    def _is_not_found(exc: ClientError) -> bool:
        error = exc.response.get("Error", {})
        code = str(error.get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return status == 404 or code in {"404", "NoSuchKey", "NotFound"}

    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer:
        try:
            url = self._client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": self._settings.storage_bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=self._settings.storage_presign_ttl_seconds,
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise ObjectStorageError("failed to sign upload") from exc
        return PresignedTransfer(
            url=url,
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=self._expiry(),
        )

    def sign_download(self, object_key: str) -> PresignedTransfer:
        try:
            url = self._client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": self._settings.storage_bucket,
                    "Key": object_key,
                },
                ExpiresIn=self._settings.storage_presign_ttl_seconds,
                HttpMethod="GET",
            )
        except Exception as exc:
            raise ObjectStorageError("failed to sign download") from exc
        return PresignedTransfer(
            url=url,
            method="GET",
            headers={},
            expires_at=self._expiry(),
        )

    def stat_object(self, object_key: str) -> StoredObject:
        try:
            response = self._client.head_object(
                Bucket=self._settings.storage_bucket,
                Key=object_key,
            )
        except ClientError as exc:
            if self._is_not_found(exc):
                raise ObjectNotFound("object not found") from exc
            raise ObjectStorageError("failed to inspect object") from exc
        except Exception as exc:
            raise ObjectStorageError("failed to inspect object") from exc

        etag = response.get("ETag")
        if isinstance(etag, str):
            etag = etag.strip('"') or None
        else:
            etag = None
        return StoredObject(
            size_bytes=int(response.get("ContentLength", -1)),
            content_type=str(response.get("ContentType") or "").lower(),
            etag=etag,
        )

    def read_prefix(self, object_key: str, max_bytes: int) -> bytes:
        # [人工注释][S1-004][S1-005] 只读取极小文件头用于类型真实性校验，
        # 不做 OCR/Vision/ASR；语义处理只发生在已 READY 的 final 对象上。
        if max_bytes <= 0:
            return b""
        try:
            response = self._client.get_object(
                Bucket=self._settings.storage_bucket,
                Key=object_key,
                Range=f"bytes=0-{max_bytes - 1}",
            )
            body = response["Body"]
            try:
                return bytes(body.read(max_bytes))
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except ClientError as exc:
            if self._is_not_found(exc):
                raise ObjectNotFound("object not found") from exc
            raise ObjectStorageError("failed to read object prefix") from exc
        except Exception as exc:
            raise ObjectStorageError("failed to read object prefix") from exc

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        # [人工注释][S1-007] ASR 只允许后端读取当前用户已 READY 的 final 音频。
        # 读取上限由服务端 media_max_audio_bytes 控制，多 1 字节探测超限，避免无界下载。
        if max_bytes <= 0:
            return b""
        try:
            response = self._client.get_object(
                Bucket=self._settings.storage_bucket,
                Key=object_key,
            )
            body = response["Body"]
            try:
                data = bytes(body.read(max_bytes + 1))
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except ClientError as exc:
            if self._is_not_found(exc):
                raise ObjectNotFound("object not found") from exc
            raise ObjectStorageError("failed to read object") from exc
        except Exception as exc:
            raise ObjectStorageError("failed to read object") from exc
        if len(data) > max_bytes:
            raise ObjectStorageError("object exceeds bounded read")
        return data

    def promote_object(self, source_key: str, destination_key: str) -> None:
        # [人工注释][S1-006] 晋升由服务端凭证执行，客户端拿不到 final key 的写权限。
        try:
            self._client.copy_object(
                Bucket=self._settings.storage_bucket,
                CopySource={
                    "Bucket": self._settings.storage_bucket,
                    "Key": source_key,
                },
                Key=destination_key,
                MetadataDirective="COPY",
            )
        except ClientError as exc:
            if self._is_not_found(exc):
                raise ObjectNotFound("source object not found") from exc
            raise ObjectStorageError("failed to promote object") from exc
        except Exception as exc:
            raise ObjectStorageError("failed to promote object") from exc

    def delete_object(self, object_key: str) -> None:
        try:
            self._client.delete_object(
                Bucket=self._settings.storage_bucket,
                Key=object_key,
            )
        except Exception as exc:
            raise ObjectStorageError("failed to delete object") from exc


@lru_cache
def get_object_storage() -> ObjectStorage:
    # [人工注释][S1-006] 存储驱动由服务端配置唯一决定，客户端不能选择 endpoint/bucket/provider。
    settings = get_settings()
    if settings.storage_backend == "disabled":
        return DisabledObjectStorage()
    if settings.storage_backend == "s3":
        return S3ObjectStorage(settings)
    raise ObjectStorageError("unsupported storage backend")
