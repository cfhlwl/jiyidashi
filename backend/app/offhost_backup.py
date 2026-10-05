from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

MANIFEST_VERSION = 1
TOOL_VERSION = "ops-003-v1"
BACKUP_ID_RE = re.compile(r"^pg-[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[A-Za-z0-9._-]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RELEASE_RE = re.compile(r"^(?:unknown|[0-9a-f]{7,64})$")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "access_key",
    "credential",
    "token",
    "jwt",
    "connection_url",
    "database_url",
)


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredBackupObject:
    key: str
    size_bytes: int
    metadata: dict[str, str]
    last_modified: datetime | None = None


class BackupStore(Protocol):
    def put_file(
        self,
        *,
        key: str,
        path: Path,
        metadata: dict[str, str],
        content_type: str,
    ) -> None: ...

    def put_bytes(
        self,
        *,
        key: str,
        body: bytes,
        metadata: dict[str, str],
        content_type: str,
    ) -> None: ...

    def head(self, key: str) -> StoredBackupObject | None: ...

    def read_bytes(self, key: str, *, max_bytes: int) -> bytes: ...

    def download(self, key: str, destination: Path) -> None: ...

    def copy(self, source_key: str, destination_key: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str) -> list[StoredBackupObject]: ...


@dataclass(frozen=True)
class BackupConfig:
    enabled: bool
    bucket: str
    region: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    addressing_style: str
    prefix: str
    source_cluster_id: str
    source_database: str
    retention_daily: int
    retention_weekly: int
    retention_monthly: int

    @classmethod
    def from_env(cls) -> BackupConfig:
        return cls(
            enabled=_env_bool("BACKUP_OFFHOST_ENABLED", default=False),
            bucket=os.getenv("BACKUP_STORAGE_BUCKET", "").strip(),
            region=os.getenv("BACKUP_STORAGE_REGION", "").strip(),
            endpoint_url=os.getenv("BACKUP_STORAGE_ENDPOINT_URL", "").strip(),
            access_key_id=os.getenv("BACKUP_STORAGE_ACCESS_KEY_ID", "").strip(),
            secret_access_key=os.getenv("BACKUP_STORAGE_SECRET_ACCESS_KEY", "").strip(),
            addressing_style=os.getenv(
                "BACKUP_STORAGE_ADDRESSING_STYLE",
                "virtual",
            ).strip(),
            prefix=os.getenv("BACKUP_OBJECT_PREFIX", "postgresql-backups").strip(),
            source_cluster_id=os.getenv("BACKUP_SOURCE_CLUSTER_ID", "").strip(),
            source_database=os.getenv("POSTGRES_DB", "").strip(),
            retention_daily=_env_int("BACKUP_RETENTION_DAILY", default=14),
            retention_weekly=_env_int("BACKUP_RETENTION_WEEKLY", default=8),
            retention_monthly=_env_int("BACKUP_RETENTION_MONTHLY", default=12),
        )

    def validate(self) -> None:
        if not self.enabled:
            raise BackupError("OFFHOST_BACKUP_DISABLED")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", self.bucket):
            raise BackupError("BACKUP_BUCKET_INVALID")
        if not SAFE_TOKEN_RE.fullmatch(self.region):
            raise BackupError("BACKUP_REGION_INVALID")
        if not self.endpoint_url.startswith("https://"):
            raise BackupError("BACKUP_ENDPOINT_HTTPS_REQUIRED")
        if not self.access_key_id or not self.secret_access_key:
            raise BackupError("BACKUP_CREDENTIALS_REQUIRED")
        for value in (
            self.bucket,
            self.region,
            self.access_key_id,
            self.secret_access_key,
            self.source_cluster_id,
        ):
            if value.startswith("CHANGE_ME"):
                raise BackupError("BACKUP_PLACEHOLDER_CONFIGURATION_REJECTED")
        if self.addressing_style not in {"virtual", "path"}:
            raise BackupError("BACKUP_ADDRESSING_STYLE_INVALID")
        _canonical_prefix(self.prefix)
        if not SAFE_TOKEN_RE.fullmatch(self.source_cluster_id):
            raise BackupError("BACKUP_SOURCE_CLUSTER_ID_INVALID")
        if not SAFE_TOKEN_RE.fullmatch(self.source_database):
            raise BackupError("BACKUP_SOURCE_DATABASE_INVALID")
        for value, name in (
            (self.retention_daily, "BACKUP_RETENTION_DAILY"),
            (self.retention_weekly, "BACKUP_RETENTION_WEEKLY"),
            (self.retention_monthly, "BACKUP_RETENTION_MONTHLY"),
        ):
            if not 1 <= value <= 3650:
                raise BackupError(f"{name}_OUT_OF_RANGE")


@dataclass(frozen=True)
class VerifiedBackup:
    backup_id: str
    scheduled_slot: datetime
    manifest_key: str
    dump_key: str
    dump_sha256: str
    dump_size_bytes: int
    schema_revision: str
    source_database: str


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise BackupError(f"{name}_INVALID_BOOLEAN")


def _env_int(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise BackupError(f"{name}_INVALID_INTEGER") from exc


def _canonical_prefix(value: str) -> str:
    normalized = value.strip().strip("/")
    if not normalized or ".." in PurePosixPath(normalized).parts:
        raise BackupError("BACKUP_PREFIX_INVALID")
    for part in PurePosixPath(normalized).parts:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", part):
            raise BackupError("BACKUP_PREFIX_INVALID")
    return normalized


def _validate_backup_id(value: str) -> str:
    if not BACKUP_ID_RE.fullmatch(value):
        raise BackupError("BACKUP_ID_INVALID")
    return value


def _parse_slot(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupError("BACKUP_SLOT_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BackupError("BACKUP_SLOT_TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _assert_manifest_safe(value: object, *, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower().replace("-", "_")
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                raise BackupError("MANIFEST_SENSITIVE_KEY_REJECTED")
            _assert_manifest_safe(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_manifest_safe(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        lowered = value.lower()
        if "://" in value and "@" in value:
            raise BackupError("MANIFEST_CREDENTIAL_URL_REJECTED")
        if "-----begin " in lowered or "\n" in value or "\r" in value:
            raise BackupError("MANIFEST_UNSAFE_STRING_REJECTED")


def _object_keys(prefix: str, backup_id: str) -> tuple[str, str, str]:
    canonical = _canonical_prefix(prefix)
    backup_id = _validate_backup_id(backup_id)
    staging = f"{canonical}/_staging/{backup_id}/database.dump"
    final_dump = f"{canonical}/verified/{backup_id}/database.dump"
    manifest = f"{canonical}/verified/{backup_id}/manifest.json"
    return staging, final_dump, manifest


class S3BackupStore:
    def __init__(self, config: BackupConfig):
        self._bucket = config.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": config.addressing_style},
            ),
        )

    def put_file(
        self,
        *,
        key: str,
        path: Path,
        metadata: dict[str, str],
        content_type: str,
    ) -> None:
        try:
            with path.open("rb") as handle:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=handle,
                    ContentType=content_type,
                    Metadata=metadata,
                )
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_PUT_FAILED") from exc

    def put_bytes(
        self,
        *,
        key: str,
        body: bytes,
        metadata: dict[str, str],
        content_type: str,
    ) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata=metadata,
            )
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_PUT_FAILED") from exc

    def head(self, key: str) -> StoredBackupObject | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise BackupError("BACKUP_STORAGE_HEAD_FAILED") from exc
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_HEAD_FAILED") from exc
        return StoredBackupObject(
            key=key,
            size_bytes=int(response.get("ContentLength", -1)),
            metadata={
                str(k).lower(): str(v)
                for k, v in dict(response.get("Metadata") or {}).items()
            },
            last_modified=response.get("LastModified"),
        )

    def read_bytes(self, key: str, *, max_bytes: int) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise BackupError("BACKUP_STORAGE_READ_FAILED") from exc
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_READ_FAILED") from exc
        body = response["Body"]
        try:
            data = bytes(body.read(max_bytes + 1))
        finally:
            body.close()
        if len(data) > max_bytes:
            raise BackupError("BACKUP_STORAGE_READ_TOO_LARGE")
        return data

    def download(self, key: str, destination: Path) -> None:
        try:
            with destination.open("wb") as handle:
                self._client.download_fileobj(self._bucket, key, handle)
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_DOWNLOAD_FAILED") from exc

    def copy(self, source_key: str, destination_key: str) -> None:
        try:
            self._client.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": source_key},
                Key=destination_key,
                MetadataDirective="COPY",
            )
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_COPY_FAILED") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_DELETE_FAILED") from exc

    def list(self, prefix: str) -> list[StoredBackupObject]:
        result: list[StoredBackupObject] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = item.get("Key")
                    if not isinstance(key, str) or not key:
                        continue
                    result.append(
                        StoredBackupObject(
                            key=key,
                            size_bytes=int(item.get("Size", -1)),
                            metadata={},
                            last_modified=item.get("LastModified"),
                        )
                    )
        except Exception as exc:
            raise BackupError("BACKUP_STORAGE_LIST_FAILED") from exc
        return result


class FilesystemBackupStore:
    """Deterministic CI seam. Production code refuses to select it from env."""

    def __init__(self, root: Path):
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if self._root not in candidate.parents:
            raise BackupError("BACKUP_FAKE_PATH_ESCAPE")
        return candidate

    def _meta_path(self, key: str) -> Path:
        path = self._path(key)
        return path.with_name(path.name + ".opsmeta.json")

    def _write_meta(
        self,
        key: str,
        *,
        metadata: dict[str, str],
        content_type: str,
    ) -> None:
        path = self._meta_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"content_type": content_type, "metadata": metadata},
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    def put_file(
        self,
        *,
        key: str,
        path: Path,
        metadata: dict[str, str],
        content_type: str,
    ) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        self._write_meta(key, metadata=metadata, content_type=content_type)

    def put_bytes(
        self,
        *,
        key: str,
        body: bytes,
        metadata: dict[str, str],
        content_type: str,
    ) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        self._write_meta(key, metadata=metadata, content_type=content_type)

    def head(self, key: str) -> StoredBackupObject | None:
        path = self._path(key)
        if not path.is_file():
            return None
        metadata: dict[str, str] = {}
        meta_path = self._meta_path(key)
        if meta_path.is_file():
            body = json.loads(meta_path.read_text(encoding="utf-8"))
            metadata = {
                str(k).lower(): str(v)
                for k, v in dict(body.get("metadata") or {}).items()
            }
        return StoredBackupObject(
            key=key,
            size_bytes=path.stat().st_size,
            metadata=metadata,
            last_modified=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
        )

    def read_bytes(self, key: str, *, max_bytes: int) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise BackupError("BACKUP_OBJECT_NOT_FOUND")
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise BackupError("BACKUP_STORAGE_READ_TOO_LARGE")
        return data

    def download(self, key: str, destination: Path) -> None:
        source = self._path(key)
        if not source.is_file():
            raise BackupError("BACKUP_OBJECT_NOT_FOUND")
        shutil.copyfile(source, destination)

    def copy(self, source_key: str, destination_key: str) -> None:
        source = self._path(source_key)
        if not source.is_file():
            raise BackupError("BACKUP_OBJECT_NOT_FOUND")
        destination = self._path(destination_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        source_meta = self._meta_path(source_key)
        if source_meta.is_file():
            target_meta = self._meta_path(destination_key)
            target_meta.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_meta, target_meta)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
        self._meta_path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[StoredBackupObject]:
        base = self._path(prefix)
        if not base.exists():
            return []
        result: list[StoredBackupObject] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name.endswith(".opsmeta.json"):
                continue
            key = path.relative_to(self._root).as_posix()
            head = self.head(key)
            if head is not None:
                result.append(head)
        return result


def _select_store(
    config: BackupConfig,
    *,
    test_filesystem_root: str | None,
) -> BackupStore:
    if test_filesystem_root:
        if os.getenv("CI", "").lower() != "true":
            raise BackupError("FILESYSTEM_BACKUP_SEAM_CI_ONLY")
        return FilesystemBackupStore(Path(test_filesystem_root))
    config.validate()
    return S3BackupStore(config)


def _expected_metadata(
    *,
    backup_id: str,
    sha256: str,
    size_bytes: int,
) -> dict[str, str]:
    return {
        "backup-id": backup_id,
        "sha256": sha256,
        "size-bytes": str(size_bytes),
        "tool-version": TOOL_VERSION,
    }


def _validate_dump_head(
    head: StoredBackupObject | None,
    *,
    backup_id: str,
    sha256: str,
    size_bytes: int,
) -> None:
    if head is None:
        raise BackupError("BACKUP_DUMP_NOT_FOUND")
    if head.size_bytes != size_bytes:
        raise BackupError("BACKUP_DUMP_SIZE_MISMATCH")
    expected = _expected_metadata(
        backup_id=backup_id,
        sha256=sha256,
        size_bytes=size_bytes,
    )
    for key, value in expected.items():
        if head.metadata.get(key) != value:
            raise BackupError("BACKUP_DUMP_METADATA_MISMATCH")


def _manifest_from_bytes(body: bytes, *, expected_id: str) -> dict[str, object]:
    try:
        manifest = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("BACKUP_MANIFEST_INVALID_JSON") from exc
    if not isinstance(manifest, dict):
        raise BackupError("BACKUP_MANIFEST_INVALID")
    _assert_manifest_safe(manifest)
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise BackupError("BACKUP_MANIFEST_VERSION_UNSUPPORTED")
    if manifest.get("backup_id") != expected_id:
        raise BackupError("BACKUP_MANIFEST_IDENTITY_MISMATCH")
    return manifest


def _verified_from_manifest(
    manifest: dict[str, object],
    *,
    prefix: str,
) -> VerifiedBackup:
    backup_id = _validate_backup_id(str(manifest.get("backup_id", "")))
    _, expected_dump, expected_manifest = _object_keys(prefix, backup_id)
    dump = manifest.get("dump")
    if not isinstance(dump, dict):
        raise BackupError("BACKUP_MANIFEST_DUMP_INVALID")
    dump_key = str(dump.get("object_key", ""))
    sha256 = str(dump.get("sha256", ""))
    try:
        size_bytes = int(dump.get("size_bytes", -1))
    except (TypeError, ValueError) as exc:
        raise BackupError("BACKUP_MANIFEST_SIZE_INVALID") from exc
    if dump_key != expected_dump:
        raise BackupError("BACKUP_MANIFEST_DUMP_KEY_AMBIGUOUS")
    if not SHA256_RE.fullmatch(sha256) or size_bytes <= 0:
        raise BackupError("BACKUP_MANIFEST_DUMP_INVALID")
    scheduled_slot = _parse_slot(str(manifest.get("scheduled_slot", "")))
    schema_revision = str(manifest.get("schema_revision", ""))
    source_database = str(manifest.get("source_database", ""))
    if not SAFE_TOKEN_RE.fullmatch(schema_revision):
        raise BackupError("BACKUP_MANIFEST_SCHEMA_REVISION_INVALID")
    if not SAFE_TOKEN_RE.fullmatch(source_database):
        raise BackupError("BACKUP_MANIFEST_SOURCE_DATABASE_INVALID")
    return VerifiedBackup(
        backup_id=backup_id,
        scheduled_slot=scheduled_slot,
        manifest_key=expected_manifest,
        dump_key=dump_key,
        dump_sha256=sha256,
        dump_size_bytes=size_bytes,
        schema_revision=schema_revision,
        source_database=source_database,
    )


def verify_backup(
    store: BackupStore,
    config: BackupConfig,
    *,
    backup_id: str,
) -> VerifiedBackup:
    _, _, manifest_key = _object_keys(config.prefix, backup_id)
    body = store.read_bytes(manifest_key, max_bytes=64 * 1024)
    manifest = _manifest_from_bytes(body, expected_id=backup_id)
    verified = _verified_from_manifest(manifest, prefix=config.prefix)
    _validate_dump_head(
        store.head(verified.dump_key),
        backup_id=verified.backup_id,
        sha256=verified.dump_sha256,
        size_bytes=verified.dump_size_bytes,
    )
    return verified


def publish_backup(
    store: BackupStore,
    config: BackupConfig,
    *,
    dump_path: Path,
    backup_id: str,
    scheduled_slot: datetime,
    release_revision: str,
    schema_revision: str,
    pg_dump_version: str,
) -> tuple[VerifiedBackup, bool]:
    backup_id = _validate_backup_id(backup_id)
    if not dump_path.is_file():
        raise BackupError("BACKUP_DUMP_FILE_MISSING")
    dump_sha256, dump_size_bytes = _sha256_file(dump_path)
    if dump_size_bytes <= 0:
        raise BackupError("BACKUP_DUMP_EMPTY")
    staging_key, final_dump_key, manifest_key = _object_keys(
        config.prefix,
        backup_id,
    )

    existing_manifest = store.head(manifest_key)
    if existing_manifest is not None:
        return verify_backup(store, config, backup_id=backup_id), False

    metadata = _expected_metadata(
        backup_id=backup_id,
        sha256=dump_sha256,
        size_bytes=dump_size_bytes,
    )
    store.put_file(
        key=staging_key,
        path=dump_path,
        metadata=metadata,
        content_type="application/octet-stream",
    )
    _validate_dump_head(
        store.head(staging_key),
        backup_id=backup_id,
        sha256=dump_sha256,
        size_bytes=dump_size_bytes,
    )

    store.copy(staging_key, final_dump_key)
    _validate_dump_head(
        store.head(final_dump_key),
        backup_id=backup_id,
        sha256=dump_sha256,
        size_bytes=dump_size_bytes,
    )

    normalized_release = release_revision.strip() or "unknown"
    if not RELEASE_RE.fullmatch(normalized_release):
        raise BackupError("BACKUP_RELEASE_REVISION_INVALID")
    if not SAFE_TOKEN_RE.fullmatch(schema_revision.strip()):
        raise BackupError("BACKUP_SCHEMA_REVISION_INVALID")

    manifest: dict[str, object] = {
        "manifest_version": MANIFEST_VERSION,
        "backup_id": backup_id,
        "created_at": _iso(datetime.now(UTC)),
        "scheduled_slot": _iso(scheduled_slot),
        "source_database": config.source_database,
        "source_cluster_id": config.source_cluster_id,
        "release_revision": normalized_release,
        "schema_revision": schema_revision.strip(),
        "pg_dump_version": pg_dump_version.strip(),
        "compression_format": "postgres-custom",
        "tool_version": TOOL_VERSION,
        "dump": {
            "object_key": final_dump_key,
            "size_bytes": dump_size_bytes,
            "sha256": dump_sha256,
        },
    }
    _assert_manifest_safe(manifest)
    verified = _verified_from_manifest(manifest, prefix=config.prefix)
    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    manifest_sha = _sha256_bytes(manifest_bytes)
    store.put_bytes(
        key=manifest_key,
        body=manifest_bytes,
        metadata={
            "backup-id": backup_id,
            "sha256": manifest_sha,
            "tool-version": TOOL_VERSION,
        },
        content_type="application/json",
    )
    manifest_head = store.head(manifest_key)
    if (
        manifest_head is None
        or manifest_head.size_bytes != len(manifest_bytes)
        or manifest_head.metadata.get("sha256") != manifest_sha
    ):
        raise BackupError("BACKUP_MANIFEST_REVALIDATION_FAILED")

    verified = verify_backup(store, config, backup_id=backup_id)
    store.delete(staging_key)
    return verified, True


def fetch_verified_backup(
    store: BackupStore,
    config: BackupConfig,
    *,
    backup_id: str,
    destination: Path,
    manifest_destination: Path | None = None,
) -> VerifiedBackup:
    verified = verify_backup(store, config, backup_id=backup_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        store.download(verified.dump_key, temporary)
        sha256, size_bytes = _sha256_file(temporary)
        if sha256 != verified.dump_sha256 or size_bytes != verified.dump_size_bytes:
            raise BackupError("BACKUP_DOWNLOAD_CHECKSUM_MISMATCH")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    if manifest_destination is not None:
        body = store.read_bytes(verified.manifest_key, max_bytes=64 * 1024)
        manifest_destination.parent.mkdir(parents=True, exist_ok=True)
        manifest_destination.write_bytes(body)
    return verified


def _list_verified_backups(
    store: BackupStore,
    config: BackupConfig,
) -> list[VerifiedBackup]:
    prefix = f"{_canonical_prefix(config.prefix)}/verified/"
    candidates = [
        item
        for item in store.list(prefix)
        if item.key.endswith("/manifest.json")
    ]
    verified: list[VerifiedBackup] = []
    for item in candidates:
        parts = PurePosixPath(item.key).parts
        if len(parts) < 3:
            raise BackupError("BACKUP_RETENTION_AMBIGUOUS_MANIFEST")
        backup_id = parts[-2]
        try:
            expected = _object_keys(config.prefix, backup_id)[2]
        except BackupError as exc:
            raise BackupError("BACKUP_RETENTION_AMBIGUOUS_MANIFEST") from exc
        if item.key != expected:
            raise BackupError("BACKUP_RETENTION_AMBIGUOUS_MANIFEST")
        verified.append(verify_backup(store, config, backup_id=backup_id))
    return sorted(verified, key=lambda item: item.scheduled_slot, reverse=True)


def latest_backup(store: BackupStore, config: BackupConfig) -> VerifiedBackup:
    backups = _list_verified_backups(store, config)
    if not backups:
        raise BackupError("NO_VERIFIED_BACKUP")
    return backups[0]


def _retention_keep_ids(
    backups: list[VerifiedBackup],
    config: BackupConfig,
) -> set[str]:
    if not backups:
        return set()
    keep = {backups[0].backup_id}
    policies = (
        (config.retention_daily, lambda dt: dt.date().isoformat()),
        (
            config.retention_weekly,
            lambda dt: f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}",
        ),
        (config.retention_monthly, lambda dt: f"{dt.year:04d}-{dt.month:02d}"),
    )
    for limit, bucket_key in policies:
        seen: set[str] = set()
        for backup in backups:
            generation = bucket_key(backup.scheduled_slot)
            if generation in seen:
                continue
            seen.add(generation)
            keep.add(backup.backup_id)
            if len(seen) >= limit:
                break
    return keep


def apply_retention(
    store: BackupStore,
    config: BackupConfig,
) -> tuple[int, int]:
    backups = _list_verified_backups(store, config)
    if not backups:
        return 0, 0
    keep = _retention_keep_ids(backups, config)
    deleted = 0
    for backup in backups:
        if backup.backup_id in keep:
            continue
        # Manifest disappears first. A crash may leave an orphan dump, but never
        # an advertised manifest that points at a deleted object.
        store.delete(backup.manifest_key)
        store.delete(backup.dump_key)
        deleted += 1
    return len(keep), deleted


def _test_store_root(value: str | None) -> str | None:
    if value is None:
        return None
    root = str(Path(value).resolve())
    if os.getenv("CI", "").lower() != "true":
        raise BackupError("FILESYSTEM_BACKUP_SEAM_CI_ONLY")
    return root


def _cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JiYiDashi off-host backup authority")
    parser.add_argument("--test-filesystem-root")
    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish")
    publish.add_argument("--dump", required=True)
    publish.add_argument("--backup-id", required=True)
    publish.add_argument("--scheduled-slot", required=True)
    publish.add_argument("--release-revision", default="unknown")
    publish.add_argument("--schema-revision", required=True)
    publish.add_argument("--pg-dump-version", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--backup-id", required=True)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--backup-id", required=True)
    fetch.add_argument("--output", required=True)
    fetch.add_argument("--manifest-output")

    sub.add_parser("latest")
    sub.add_parser("retention")
    return parser


def main() -> None:
    parser = _cli()
    args = parser.parse_args()
    config = BackupConfig.from_env()
    test_root = _test_store_root(args.test_filesystem_root)
    store = _select_store(config, test_filesystem_root=test_root)

    if args.command == "publish":
        verified, created = publish_backup(
            store,
            config,
            dump_path=Path(args.dump),
            backup_id=args.backup_id,
            scheduled_slot=_parse_slot(args.scheduled_slot),
            release_revision=args.release_revision,
            schema_revision=args.schema_revision,
            pg_dump_version=args.pg_dump_version,
        )
        print(
            json.dumps(
                {
                    "backup_id": verified.backup_id,
                    "created": created,
                    "status": "verified",
                },
                sort_keys=True,
            )
        )
        return

    if args.command == "verify":
        verified = verify_backup(store, config, backup_id=args.backup_id)
        print(
            json.dumps(
                {"backup_id": verified.backup_id, "status": "verified"},
                sort_keys=True,
            )
        )
        return

    if args.command == "fetch":
        verified = fetch_verified_backup(
            store,
            config,
            backup_id=args.backup_id,
            destination=Path(args.output),
            manifest_destination=(
                Path(args.manifest_output)
                if args.manifest_output
                else None
            ),
        )
        print(
            json.dumps(
                {"backup_id": verified.backup_id, "status": "fetched_verified"},
                sort_keys=True,
            )
        )
        return

    if args.command == "latest":
        verified = latest_backup(store, config)
        print(verified.backup_id)
        return

    if args.command == "retention":
        kept, deleted = apply_retention(store, config)
        print(json.dumps({"deleted": deleted, "kept": kept}, sort_keys=True))
        return

    raise AssertionError("unreachable")


if __name__ == "__main__":
    try:
        main()
    except BackupError as exc:
        print(f"off-host backup: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
