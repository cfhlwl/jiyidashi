from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings


# [人工注释][S1-006] 公共 API 永远只拿短时签名请求，不暴露永久公开 URL；具体 COS/OSS/S3 兼容实现隔离在此抽象后。
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


class DisabledObjectStorage:
    # [人工注释][S1-006] 未配置对象存储时媒体接口 fail closed 返回不可用，不能偷偷退化成本机公开文件目录。
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


class S3ObjectStorage:
    # [人工注释][S1-006] 使用 S3 SigV4 兼容边界承载 COS/OSS 私有桶；签名 PUT 固定 Content-Type，
    # 完成接口随后 HEAD 服务端生成的 object_key，避免客户端自行声明“已上传”即进入 Evidence。
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
        except Exception as exc:  # boto providers expose several transport/credential errors.
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
            error = exc.response.get("Error", {})
            code = str(error.get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
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


@lru_cache
def get_object_storage() -> ObjectStorage:
    # [人工注释][S1-006] 存储驱动由服务端配置唯一决定，客户端不能选择 endpoint/bucket/provider。
    settings = get_settings()
    if settings.storage_backend == "disabled":
        return DisabledObjectStorage()
    if settings.storage_backend == "s3":
        return S3ObjectStorage(settings)
    raise ObjectStorageError("unsupported storage backend")
