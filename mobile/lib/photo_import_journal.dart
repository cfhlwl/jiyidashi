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

  Future<List<OfflineQueueItem>> list() async {
    final all = await store.listAll(ownerUserId);
    return all.where((item) => item.operationType == operationType)
        .toList(growable: false);
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

  /// Owner-scoped content dedup. A completed SHA has an authoritative memory
  /// receipt; a pending SHA is not a second upload opportunity.
  Future<OfflineQueueItem?> findSameContent(String sha256Hex) async {
    final rows = await list();
    for (final row in rows) {
      if (row.payload['sha256'] == sha256Hex &&
          row.status != OfflineQueueStatus.cancelled) {
        return row;
      }
    }
    return null;
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
    final previous = await store.findByClientUuid(ownerUserId, clientUploadId);
    if (previous != null) {
      if (previous.operationType != operationType ||
          previous.payload['sha256'] != photo.contentSha256) {
        throw StateError('photo upload UUID already belongs to different work');
      }
      return previous;
    }

    final dir = await store.photoImportOwnerDirectory(ownerUserId);
    await dir.create(recursive: true);
    final saved = File('${dir.path}${Platform.pathSeparator}$clientUploadId.bin');
    final temporary = File('${saved.path}.partial');
    var persisted = false;
    try {
      if (!await saved.exists()) {
        await File(photo.path).copy(temporary.path);
        if (await temporary.length() != photo.bytes ||
            (await sha256.bind(temporary.openRead()).first).toString() !=
                photo.contentSha256) {
          throw const FormatException('photo changed during durable copy');
        }
        await temporary.rename(saved.path);
      }
      final row = await store.enqueueLocalTask(
        ownerUserId: ownerUserId,
        operationType: operationType,
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
      persisted = true;
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
  }

  Future<OfflineQueueItem> begin(OfflineQueueItem row) async {
    if (row.ownerUserId != ownerUserId || row.operationType != operationType) {
      throw StateError('wrong photo owner');
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
