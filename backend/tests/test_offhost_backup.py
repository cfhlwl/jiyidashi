from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.offhost_backup import (
    BackupConfig,
    BackupError,
    FilesystemBackupStore,
    _object_keys,
    apply_retention,
    fetch_verified_backup,
    latest_backup,
    publish_backup,
    verify_backup,
)


def _config() -> BackupConfig:
    return BackupConfig(
        enabled=True,
        bucket="private-backups",
        region="test-region",
        endpoint_url="https://backup.example.invalid",
        access_key_id="test-access",
        secret_access_key="test-secret",
        addressing_style="virtual",
        prefix="postgresql-backups",
        source_cluster_id="prod-cluster-a",
        source_database="jiyi",
        retention_daily=2,
        retention_weekly=2,
        retention_monthly=2,
    )


def _dump(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    return path


def _publish(
    store: FilesystemBackupStore,
    config: BackupConfig,
    tmp_path: Path,
    *,
    backup_id: str,
    slot: datetime,
    body: bytes,
):
    return publish_backup(
        store,
        config,
        dump_path=_dump(tmp_path / f"{backup_id}.dump", body),
        backup_id=backup_id,
        scheduled_slot=slot,
        release_revision="a" * 40,
        schema_revision="0032_maintenance_jobs",
        pg_dump_version="pg_dump (PostgreSQL) 16.10",
    )


def test_publish_is_manifest_last_and_revalidated(tmp_path: Path):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    verified, created = _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=datetime(2026, 10, 5, tzinfo=UTC),
        body=b"postgres-custom-dump-v1",
    )

    assert created is True
    assert verify_backup(store, config, backup_id=verified.backup_id) == verified

    staging, final_dump, manifest_key = _object_keys(
        config.prefix,
        verified.backup_id,
    )
    assert store.head(staging) is None
    assert store.head(final_dump) is not None
    manifest_head = store.head(manifest_key)
    assert manifest_head is not None
    assert manifest_head.metadata["backup-id"] == verified.backup_id
    assert manifest_head.metadata["sha256"]

    manifest = json.loads(
        store.read_bytes(manifest_key, max_bytes=64 * 1024).decode("utf-8")
    )
    serialized = json.dumps(manifest, sort_keys=True)
    assert "test-secret" not in serialized
    assert "test-access" not in serialized
    assert "postgresql+psycopg://" not in serialized


def _manifest_bytes(manifest: dict[str, object]) -> bytes:
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _rewrite_manifest_with_valid_metadata(
    store: FilesystemBackupStore,
    config: BackupConfig,
    *,
    backup_id: str,
    mutate,
) -> bytes:
    _, _, manifest_key = _object_keys(config.prefix, backup_id)
    manifest = json.loads(
        store.read_bytes(manifest_key, max_bytes=64 * 1024).decode("utf-8")
    )
    mutate(manifest)
    body = _manifest_bytes(manifest)
    store.put_bytes(
        key=manifest_key,
        body=body,
        metadata={
            "backup-id": backup_id,
            "sha256": hashlib.sha256(body).hexdigest(),
            "tool-version": "ops-003-v1",
        },
        content_type="application/json",
    )
    return body


def test_partial_upload_without_manifest_is_not_valid(tmp_path: Path):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    staging, _, _ = _object_keys(config.prefix, "pg-2026-10-05")
    source = _dump(tmp_path / "partial.dump", b"partial")
    store.put_file(
        key=staging,
        path=source,
        metadata={
            "backup-id": "pg-2026-10-05",
            "sha256": "0" * 64,
            "size-bytes": str(source.stat().st_size),
            "tool-version": "ops-003-v1",
        },
        content_type="application/octet-stream",
    )

    with pytest.raises(BackupError, match="NO_VERIFIED_BACKUP"):
        latest_backup(store, config)


class CorruptingCopyStore(FilesystemBackupStore):
    def copy(self, source_key: str, destination_key: str) -> None:
        super().copy(source_key, destination_key)
        destination = self._path(destination_key)
        body = bytearray(destination.read_bytes())
        assert body
        body[0] ^= 0x01
        destination.write_bytes(body)


def test_remote_content_mismatch_never_publishes_manifest(tmp_path: Path):
    store = CorruptingCopyStore(tmp_path / "remote")
    config = _config()

    with pytest.raises(BackupError, match="BACKUP_REMOTE_CONTENT_MISMATCH"):
        _publish(
            store,
            config,
            tmp_path,
            backup_id="pg-2026-10-05",
            slot=datetime(2026, 10, 5, tzinfo=UTC),
            body=b"content-integrity-proof",
        )

    _, _, manifest_key = _object_keys(config.prefix, "pg-2026-10-05")
    assert store.head(manifest_key) is None


def test_same_slot_retry_is_idempotent_and_does_not_replace_verified_dump(
    tmp_path: Path,
):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    slot = datetime(2026, 10, 5, tzinfo=UTC)
    first, created = _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=slot,
        body=b"first-dump",
    )
    assert created is True

    second, created = _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=slot,
        body=b"different-retry-input",
    )
    assert created is False
    assert second == first

    fetched = tmp_path / "fetched.dump"
    fetch_verified_backup(
        store,
        config,
        backup_id="pg-2026-10-05",
        destination=fetched,
    )
    assert fetched.read_bytes() == b"first-dump"


@pytest.mark.parametrize(
    ("field", "foreign_value", "error_code"),
    [
        ("source_cluster_id", "prod-cluster-b", "BACKUP_MANIFEST_FOREIGN_CLUSTER"),
        ("source_database", "evil", "BACKUP_MANIFEST_FOREIGN_DATABASE"),
    ],
)
def test_foreign_manifest_is_rejected_even_with_matching_checksum_metadata(
    tmp_path: Path,
    field: str,
    foreign_value: str,
    error_code: str,
):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=datetime(2026, 10, 5, tzinfo=UTC),
        body=b"foreign-authority-test",
    )

    _rewrite_manifest_with_valid_metadata(
        store,
        config,
        backup_id="pg-2026-10-05",
        mutate=lambda manifest: manifest.__setitem__(field, foreign_value),
    )

    with pytest.raises(BackupError, match=error_code):
        verify_backup(store, config, backup_id="pg-2026-10-05")


def test_manifest_slot_date_must_match_backup_id_even_with_valid_checksum(
    tmp_path: Path,
):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=datetime(2026, 10, 5, tzinfo=UTC),
        body=b"slot-authority-test",
    )

    _rewrite_manifest_with_valid_metadata(
        store,
        config,
        backup_id="pg-2026-10-05",
        mutate=lambda manifest: manifest.__setitem__(
            "scheduled_slot",
            "2026-10-06T00:00:00Z",
        ),
    )

    with pytest.raises(BackupError, match="BACKUP_MANIFEST_SLOT_IDENTITY_MISMATCH"):
        verify_backup(store, config, backup_id="pg-2026-10-05")


@pytest.mark.parametrize(
    "operation",
    [
        "verify",
        "latest",
        "retention",
    ],
)
def test_same_size_valid_json_manifest_corruption_fails_closed(
    tmp_path: Path,
    operation: str,
):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    verified, _ = _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=datetime(2026, 10, 5, tzinfo=UTC),
        body=b"manifest-integrity-test",
    )

    manifest_path = (tmp_path / "remote" / verified.manifest_key).resolve()
    original = manifest_path.read_bytes()
    corrupted = original.replace(b"prod-cluster-a", b"prod-cluster-b", 1)
    assert corrupted != original
    assert len(corrupted) == len(original)
    json.loads(corrupted.decode("utf-8"))
    manifest_path.write_bytes(corrupted)

    with pytest.raises(BackupError, match="BACKUP_MANIFEST_CHECKSUM_MISMATCH"):
        if operation == "verify":
            verify_backup(store, config, backup_id=verified.backup_id)
        elif operation == "latest":
            latest_backup(store, config)
        else:
            apply_retention(store, config)


def test_fetch_rejects_same_size_checksum_corruption_before_publish_to_destination(
    tmp_path: Path,
):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    verified, _ = _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=datetime(2026, 10, 5, tzinfo=UTC),
        body=b"abcdefghij",
    )

    remote_dump = (tmp_path / "remote" / verified.dump_key).resolve()
    remote_dump.write_bytes(b"0123456789")
    destination = tmp_path / "restore.dump"

    with pytest.raises(BackupError, match="BACKUP_DOWNLOAD_CHECKSUM_MISMATCH"):
        fetch_verified_backup(
            store,
            config,
            backup_id=verified.backup_id,
            destination=destination,
        )

    assert not destination.exists()
    assert not destination.with_name(destination.name + ".partial").exists()


class ManifestMutatingDownloadStore(FilesystemBackupStore):
    manifest_key: str | None = None
    manifest_reads = 0

    def read_bytes(self, key: str, *, max_bytes: int) -> bytes:
        if key == self.manifest_key:
            self.manifest_reads += 1
        return super().read_bytes(key, max_bytes=max_bytes)

    def download(self, key: str, destination: Path) -> None:
        super().download(key, destination)
        if self.manifest_key is None:
            return
        manifest = json.loads(
            super().read_bytes(
                self.manifest_key,
                max_bytes=64 * 1024,
            ).decode("utf-8")
        )
        manifest["schema_revision"] = "9999_maintenance_jobs"
        body = _manifest_bytes(manifest)
        self.put_bytes(
            key=self.manifest_key,
            body=body,
            metadata={
                "backup-id": str(manifest["backup_id"]),
                "sha256": hashlib.sha256(body).hexdigest(),
                "tool-version": "ops-003-v1",
            },
            content_type="application/json",
        )


def test_fetch_exports_the_exact_manifest_bytes_that_were_verified(
    tmp_path: Path,
):
    store = ManifestMutatingDownloadStore(tmp_path / "remote")
    config = _config()
    verified, _ = _publish(
        store,
        config,
        tmp_path,
        backup_id="pg-2026-10-05",
        slot=datetime(2026, 10, 5, tzinfo=UTC),
        body=b"restore-manifest-toctou-proof",
    )
    store.manifest_key = verified.manifest_key

    destination = tmp_path / "restore.dump"
    manifest_destination = tmp_path / "restore.manifest.json"
    fetched = fetch_verified_backup(
        store,
        config,
        backup_id=verified.backup_id,
        destination=destination,
        manifest_destination=manifest_destination,
    )

    exported = json.loads(manifest_destination.read_text(encoding="utf-8"))
    remote = json.loads(
        FilesystemBackupStore.read_bytes(
            store,
            verified.manifest_key,
            max_bytes=64 * 1024,
        ).decode("utf-8")
    )

    assert fetched.schema_revision == "0032_maintenance_jobs"
    assert exported["schema_revision"] == fetched.schema_revision
    assert remote["schema_revision"] == "9999_maintenance_jobs"
    assert store.manifest_reads == 1


def test_retention_preserves_newest_and_ignores_outside_prefix(tmp_path: Path):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    slots = [
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 8, 8, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 10, 4, tzinfo=UTC),
        datetime(2026, 10, 5, tzinfo=UTC),
    ]
    for slot in slots:
        backup_id = f"pg-{slot.date().isoformat()}"
        _publish(
            store,
            config,
            tmp_path,
            backup_id=backup_id,
            slot=slot,
            body=f"dump-{backup_id}".encode(),
        )

    outside = tmp_path / "outside.txt"
    outside.write_text("must-survive", encoding="utf-8")
    store.put_file(
        key="another-prefix/verified/not-ours/database.dump",
        path=outside,
        metadata={},
        content_type="application/octet-stream",
    )

    kept, deleted = apply_retention(store, config)
    assert kept >= 1
    assert deleted >= 1

    newest = verify_backup(store, config, backup_id="pg-2026-10-05")
    assert newest.backup_id == "pg-2026-10-05"
    assert store.head("another-prefix/verified/not-ours/database.dump") is not None


def test_retention_fails_closed_on_ambiguous_manifest_identity(tmp_path: Path):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    key = f"{config.prefix}/verified/pg-2026-10-05/unexpected/manifest.json"
    store.put_bytes(
        key=key,
        body=b"{}",
        metadata={},
        content_type="application/json",
    )

    with pytest.raises(BackupError, match="BACKUP_RETENTION_AMBIGUOUS_MANIFEST"):
        apply_retention(store, config)


def test_config_fails_closed_when_enabled_credentials_are_incomplete():
    config = BackupConfig(
        enabled=True,
        bucket="",
        region="",
        endpoint_url="http://not-https.invalid",
        access_key_id="",
        secret_access_key="",
        addressing_style="virtual",
        prefix="postgresql-backups",
        source_cluster_id="prod-cluster-a",
        source_database="jiyi",
        retention_daily=14,
        retention_weekly=8,
        retention_monthly=12,
    )

    with pytest.raises(BackupError):
        config.validate()


def test_retention_weekly_and_monthly_generations_are_bounded(tmp_path: Path):
    store = FilesystemBackupStore(tmp_path / "remote")
    config = _config()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for offset in range(12):
        slot = start + timedelta(days=offset * 28)
        backup_id = f"pg-{slot.date().isoformat()}"
        _publish(
            store,
            config,
            tmp_path,
            backup_id=backup_id,
            slot=slot,
            body=f"dump-{offset}".encode(),
        )

    kept, deleted = apply_retention(store, config)
    assert kept <= (
        config.retention_daily
        + config.retention_weekly
        + config.retention_monthly
    )
    assert deleted > 0
