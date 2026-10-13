import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';

import 'offline_queue.dart';
import 'photo_import_metadata.dart';

/// The existing app SQLite outbox remains the one owner authority and account
/// deletion purge. The photo operation is EXCLUDED from background text/location
/// auto-delivery; restarting the app never silently uploads gallery assets.
class PhotoImportJournal {
  PhotoImportJournal({
    required this.store,
    required this.ownerUserId,
  });

  final OfflineQueueStore store;
  final String ownerUserId;

  static const String operationType = OfflineQueueStore.photoImportOperation;

  static Map<String, dynamic> _evidence(PhotoCaptureEvidence e) => {
    if (e.localCaptureTime != null) 'local_capture_time': e.localCaptureTime,
    if (e.captureTimeUtc != null)
      'capture_time_utc': e.captureTimeUtc!.toIso8601String(),
    if (e.utcOffsetMinutes != null) 'utc_offset_minutes': e.utcOffsetMinutes,
    if (e.hasGps) 'gps_latitude': e.latitude,
    if (e.hasGps) 'gps_longitude': e.longitude,
    if (e.orientation != null) 'orientation': e.orientation,
    if (e.metadataUnreadable) 'metadata_unreadable': true,
  };

  static PhotoCaptureEvidence _parseEvidence(Object? raw) {
    if (raw is! Map<String, dynamic>) {
      throw const FormatException('invalid saved photo evidence');
    }
    final local = raw['local_capture_time'];
    final utcRaw = raw['capture_time_utc'];
    final offset = raw['utc_offset_minutes'];
    final lat = raw['gps_latitude'];
    final lon = raw['gps_longitude'];
    return PhotoCaptureEvidence(
      localCaptureTime: local is String ? local : null,
      captureTimeUtc: utcRaw is String ? DateTime.parse(utcRaw).toUtc() : null,
      utcOffsetMinutes: offset is int ? offset : null,
      latitude: lat is num && lon is num ? lat.toDouble() : null,
      longitude: lat is num && lon is num ? lon.toDouble() : null,
      orientation: raw['orientation'] is int ? raw['orientation'] as int : null,
      metadataUnreadable: raw['metadata_unreadable'] == true,
    );
  }

  // fcntl-style OS locks may be per-process. Serialize all foreground
  // coordinators in the same isolate BEFORE acquiring the inter-process lock.
  static final Map<String, Future<void>> _ownerStageLockTails =
      <String, Future<void>>{};

  /// Serialize source staging, durable reservation and orphan reconciliation.
  /// A crashed process releases its file lock. An in-process queued operation
  /// always completes its gate (including on exceptions).
  Future<T> _withOwnerStageLock<T>(Future<T> Function() operation) async {
    final directory = await store.photoImportOwnerDirectory(ownerUserId);
    final lockKey = directory.path;
    final previous = _ownerStageLockTails[lockKey];
    final completed = Completer<void>();
    _ownerStageLockTails[lockKey] = completed.future;
    try {
      if (previous != null) {
        await previous;
      }
      // Both the owner leaf and its private photo-import parent must be real
      // directories. Checking only the leaf follows a symlinked ancestor.
      if (await FileSystemEntity.type(
            directory.parent.path,
            followLinks: false,
          ) == FileSystemEntityType.link ||
          await FileSystemEntity.type(directory.path, followLinks: false) ==
              FileSystemEntityType.link) {
        throw const FormatException('photo staging path contains a symlink');
      }
      await directory.create(recursive: true);
      if (await FileSystemEntity.type(
            directory.parent.path,
            followLinks: false,
          ) != FileSystemEntityType.directory) {
        throw const FormatException('photo staging parent is not a real directory');
      }
      if (await FileSystemEntity.type(directory.path, followLinks: false) !=
          FileSystemEntityType.directory) {
        throw const FormatException('invalid owner photo staging directory');
      }
      final lockPath = '${directory.path}${Platform.pathSeparator}.stage.lock';
      if (await FileSystemEntity.type(lockPath, followLinks: false) ==
          FileSystemEntityType.link) {
        throw const FormatException('photo staging lock is a symlink');
      }
      final handle = await File(lockPath).open(mode: FileMode.append);
      try {
        await handle.lock(FileLock.exclusive);
        try {
          return await operation();
        } finally {
          await handle.unlock();
        }
      } finally {
        await handle.close();
      }
    } finally {
      if (identical(_ownerStageLockTails[lockKey], completed.future)) {
        _ownerStageLockTails.remove(lockKey);
      }
      completed.complete();
    }
  }

  Future<List<OfflineQueueItem>> list() async {
    final all = await store.listAll(ownerUserId);
    final photos = all.where((item) => item.operationType == operationType)
        .toList(growable: false);
    if (store.supportsPhotoImportFileSweep) {
      await sweepOrphanedFiles(photos);
    }
    return photos;
  }

  Future<SelectedPhotoImport> selectedFrom(OfflineQueueItem row) async {
    if (row.ownerUserId != ownerUserId || row.operationType != operationType) {
      throw StateError('photo journal row has wrong owner or type');
    }
    final json = row.payload;
    final path = json['staged_path'];
    final filename = json['original_filename'];
    final size = json['size_bytes'];
    final contentType = json['content_type'];
    final digest = json['sha256'];
    if (path is! String || filename is! String || size is! int ||
        contentType is! String || digest is! String) {
      throw const FormatException('invalid persisted gallery row');
    }
    // Never honor a DB-provided arbitrary path. Only the exact opaque UUID
    // filename inside this row's private owner directory is permitted.
    final uuid = row.clientUuid;
    final directory = await store.photoImportOwnerDirectory(ownerUserId);
    final expected = '${directory.path}${Platform.pathSeparator}$uuid.bin';
    if (!RegExp(r'^[0-9a-fA-F-]{36}$').hasMatch(uuid) ||
        path != expected) {
      throw const FormatException('photo journal filename invalid');
    }
    return SelectedPhotoImport(
      path: path,
      originalFilename: filename,
      bytes: size,
      contentType: contentType,
      contentSha256: digest,
      evidence: _parseEvidence(json['evidence']),
    );
  }

  /// Verify the actual bytes that will be sent, not the original picker path.
  /// Keep this separate from selectedFrom(), which also feeds UI previews.
  Future<void> verifyStaged(OfflineQueueItem row) async {
    final selected = await selectedFrom(row);
    if (await FileSystemEntity.type(selected.path, followLinks: false) !=
        FileSystemEntityType.file) {
      throw const FormatException('staged photo is missing or not a regular file');
    }
    final file = File(selected.path);
    if (await file.length() != selected.bytes ||
        (await sha256.bind(file.openRead()).first).toString() !=
            selected.contentSha256) {
      throw const FormatException('staged photo fingerprint mismatch');
    }
  }

  /// Owner-scoped content dedup. A completed SHA has an authoritative memory
  /// receipt; a pending SHA is not a second upload opportunity.
  Future<OfflineQueueItem?> findSameContent(String sha256Hex) =>
      store.findClaimedPhoto(ownerUserId, sha256Hex);

  Future<void> invalidateDeletedMemory(
    OfflineQueueItem receipt, {
    required String sha256Hex,
  }) {
    if (receipt.ownerUserId != ownerUserId ||
        receipt.operationType != operationType ||
        receipt.status != OfflineQueueStatus.completed ||
        receipt.serverResourceId == null) {
      throw StateError('not an owner-completed media receipt');
    }
    return store.invalidatePhotoReceipt(
      ownerUserId: ownerUserId,
      sha256Hex: sha256Hex,
      clientUuid: receipt.clientUuid,
      serverResourceId: receipt.serverResourceId!,
    );
  }

  Future<OfflineQueueItem> stage(
    SelectedPhotoImport photo, {
    required String clientUploadId,
  }) async {
    if (!RegExp(r'^[0-9a-fA-F-]{36}$').hasMatch(clientUploadId) ||
        photo.bytes <= 0 || photo.bytes > PhotoImportPicker.maxBytesPerPhoto ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(photo.contentSha256)) {
      throw ArgumentError('invalid photo import id or fingerprint');
    }
    final releaseStage = store.holdPhotoImportStaging(ownerUserId);
    try {
      return await _withOwnerStageLock(() async {
        final previous = await store.findByClientUuid(ownerUserId, clientUploadId);
        if (previous != null) {
          if (previous.operationType != operationType ||
              previous.payload['sha256'] != photo.contentSha256) {
            throw StateError('photo upload UUID already belongs to different work');
          }
          // An existing row is not proof that its private staged bytes are intact.
          // A same-length modification must fail closed on every retry.
          await verifyStaged(previous);
          return previous;
        }

        final dir = await store.photoImportOwnerDirectory(ownerUserId);
        await dir.create(recursive: true);
        if (await FileSystemEntity.type(dir.path, followLinks: false) !=
            FileSystemEntityType.directory) {
          throw const FormatException('photo staging directory is not a real directory');
        }
        final saved = File('${dir.path}${Platform.pathSeparator}$clientUploadId.bin');
        final temporary = File('${saved.path}.partial');
        var persisted = false;
        try {
          if (await FileSystemEntity.type(saved.path, followLinks: false) ==
                  FileSystemEntityType.link ||
              await FileSystemEntity.type(temporary.path, followLinks: false) ==
                  FileSystemEntityType.link) {
            throw const FormatException('photo staging path is a symlink');
          }
          if (!await saved.exists()) {
            await File(photo.path).copy(temporary.path);
            if (await temporary.length() != photo.bytes ||
                (await sha256.bind(temporary.openRead()).first).toString() !=
                    photo.contentSha256) {
              throw const FormatException('photo changed during durable copy');
            }
            await temporary.rename(saved.path);
          }
          // A leftover cache copy from an interrupted process is not trusted just
          // because its path matches. Rehash even the already-staged file.
          if (await saved.length() != photo.bytes ||
              (await sha256.bind(saved.openRead()).first).toString() !=
                  photo.contentSha256) {
            throw const FormatException('staged photo fingerprint mismatch');
          }
          final row = await store.reservePhotoImport(
            ownerUserId: ownerUserId,
            sha256Hex: photo.contentSha256,
            clientUuid: clientUploadId,
            payload: {
              'staged_path': saved.path,
              'original_filename': photo.originalFilename,
              'size_bytes': photo.bytes,
              'content_type': photo.contentType,
              'sha256': photo.contentSha256,
              'evidence': _evidence(photo.evidence),
            },
          );
          persisted = row.clientUuid == clientUploadId;
          return row;
        } finally {
          if (await temporary.exists()) {
            await temporary.delete();
          }
          if (!persisted && await saved.exists()) {
            // Failed DB write or owner deletion quiesce cannot strand bytes.
            await saved.delete();
          }
        }
      });
    } finally {
      releaseStage();
    }
  }

  /// A killed process cannot run a finally block after copy/rename. Sweep
  /// only unreferenced, old regular UUID stage files belonging to this owner.
  /// The grace period protects concurrently staging processes; any referenced
  /// pending/sending/failed row is ALWAYS retained, independent of its age.
  /// No recursive traversal and no following symlinks.
  Future<int> sweepOrphanedFiles(
    List<OfflineQueueItem> allRows, {
    Duration gracePeriod = const Duration(hours: 1),
    DateTime? now,
  }) async {
    return _withOwnerStageLock(() async {
      if (gracePeriod < Duration.zero) {
        throw ArgumentError('negative grace period');
      }
      final dir = await store.photoImportOwnerDirectory(ownerUserId);
      if (await FileSystemEntity.type(dir.path, followLinks: false) !=
          FileSystemEntityType.directory) {
        return 0;
      }
      final referenced = <String>{
        for (final row in allRows)
          if (row.operationType == operationType &&
              row.status != OfflineQueueStatus.cancelled &&
              row.status != OfflineQueueStatus.completed)
            row.clientUuid.toLowerCase(),
      };
      final cutoff = (now ?? DateTime.now()).toUtc().subtract(gracePeriod);
      var deleted = 0;
      await for (final entity in dir.list(followLinks: false)) {
        if (await FileSystemEntity.type(entity.path, followLinks: false) !=
            FileSystemEntityType.file) {
          continue;
        }
        final basename = entity.uri.pathSegments.last;
        final match = RegExp(
          r'^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.bin(\.partial)?$',
        ).firstMatch(basename);
        if (match == null ||
            referenced.contains(match.group(1)!.toLowerCase())) {
          continue;
        }
        final file = File(entity.path);
        final stat = await file.stat();
        if (!stat.modified.toUtc().isBefore(cutoff)) {
          continue;
        }
        // Second check prevents a referenced item being removed if another
        // SQLite writer committed during directory enumeration.
        final existing = await store.findByClientUuid(ownerUserId, match.group(1)!);
        if (existing != null && existing.operationType == operationType &&
            existing.status != OfflineQueueStatus.cancelled &&
            existing.status != OfflineQueueStatus.completed) {
          continue;
        }
        if (await FileSystemEntity.type(file.path, followLinks: false) ==
            FileSystemEntityType.file) {
          await file.delete();
          deleted++;
        }
      }
      return deleted;
    });
  }

  Future<void> withdraw(OfflineQueueItem row) async {
    if (row.ownerUserId != ownerUserId || row.operationType != operationType) {
      throw StateError('photo withdraw owner mismatch');
    }
    if (row.status != OfflineQueueStatus.pending &&
        row.status != OfflineQueueStatus.failed &&
        row.status != OfflineQueueStatus.cancelled) {
      throw StateError('in-flight or completed media cannot be withdrawn');
    }
    final source = await selectedFrom(row);
    await store.cancel(ownerUserId, row.clientUuid);
    final staged = File(source.path);
    if (await staged.exists()) {
      await staged.delete();
    }
  }

  Future<OfflineQueueItem> begin(OfflineQueueItem row) async {
    if (row.ownerUserId != ownerUserId || row.operationType != operationType) {
      throw StateError('wrong photo owner');
    }
    final digest = row.payload['sha256'];
    if (digest is! String) {
      throw const FormatException('invalid photo SHA claim');
    }
    final claim = await store.findClaimedPhoto(ownerUserId, digest);
    if (claim?.clientUuid != row.clientUuid) {
      throw StateError('photo UUID is not owner-SHA active claim');
    }
    if (row.status == OfflineQueueStatus.failed) {
      await store.retryFailed(ownerUserId, row.clientUuid);
    }
    return store.markSending(ownerUserId, row.clientUuid);
  }

  Future<OfflineQueueItem> failed(OfflineQueueItem row) =>
      store.markFailed(
        ownerUserId, row.clientUuid,
        'PHOTO_IMPORT_RETRY_REQUIRED',
        retryable: true,
      );

  Future<OfflineQueueItem> complete(
    OfflineQueueItem row, {
    required String memoryId,
  }) async {
    final completed = await store.markCompleted(
      ownerUserId, row.clientUuid,
      serverResourceId: memoryId,
    );
    // Durable completed receipt precedes file deletion. Failure to clean a
    // cache copy must never turn a confirmed server memory into false failure.
    try {
      final source = await selectedFrom(completed);
      final file = File(source.path);
      if (await file.exists()) {
        await file.delete();
      }
    } catch (_) {}
    return completed;
  }
}

