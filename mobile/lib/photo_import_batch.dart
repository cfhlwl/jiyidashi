import 'dart:io';

import 'package:crypto/crypto.dart';

import 'capture_media.dart';
import 'api_client.dart';
import 'photo_import_metadata.dart';

/// In-memory coordinator for one user-approved picker selection.
///
/// It deliberately does not pretend to be a crash-durable offline queue.
/// Import remains a preview/foreground-only feature until an owner-scoped
/// persisted journal is integrated. The existing media upload protocol itself
/// is idempotent for a stable clientUploadId.
enum PhotoImportItemState { waiting, uploading, verifying, saving, saved, failed }

class PhotoImportBatchItem {
  PhotoImportBatchItem(this.selected) : clientUploadId = newCaptureClientUuid();

  final SelectedPhotoImport selected;
  final String clientUploadId;
  PhotoImportItemState state = PhotoImportItemState.waiting;
  String? memoryId;
  String? errorCode;
}

class PhotoImportBatchCoordinator {
  PhotoImportBatchCoordinator({
    required this.api,
    required PhotoImportSelection selection,
    TrustedMediaCaptureService? service,
    Future<bool> Function(SelectedPhotoImport)? verifySelection,
  }) : _service = service ?? TrustedMediaCaptureService(api),
       _verifySelection = verifySelection ?? _verifySourceFingerprint,
       items = List.unmodifiable(
         selection.selected.map(PhotoImportBatchItem.new),
       ),
       _owner = _requireOwner(api),
       _sessionVersion = api.sessionVersion;

  final JiYiApiClient api;
  final TrustedMediaCaptureService _service;
  final Future<bool> Function(SelectedPhotoImport) _verifySelection;
  final List<PhotoImportBatchItem> items;
  final String _owner;
  final int _sessionVersion;

  bool _running = false;
  bool _stopRequested = false;

  bool get isRunning => _running;
  bool get stopRequested => _stopRequested;
  int get savedCount =>
      items.where((item) => item.state == PhotoImportItemState.saved).length;
  int get failedCount =>
      items.where((item) => item.state == PhotoImportItemState.failed).length;

  static Future<bool> _verifySourceFingerprint(SelectedPhotoImport item) async {
    final file = File(item.path);
    if (await file.length() != item.bytes) return false;
    final digest = (await sha256.bind(file.openRead()).first).toString();
    return digest == item.contentSha256;
  }

  static String _requireOwner(JiYiApiClient api) {
    final owner = api.authenticatedUserId?.trim();
    if (owner == null || owner.isEmpty) {
      throw ApiException(401, '请先登录');
    }
    return owner;
  }

  void _assertOwner() {
    if (api.sessionVersion != _sessionVersion ||
        api.authenticatedUserId != _owner) {
      throw ProtocolException('照片导入账号已变化，请重新选择本账号照片');
    }
  }

  void stopAfterCurrentFile() => _stopRequested = true;

  /// Sequential upload limits network/memory pressure. Each completed item is
  /// a real server memory; cancellation never rewrites it as failed/skipped.
  /// Restarting the same live coordinator preserves original upload UUIDs.
  Future<void> submit({
    void Function(PhotoImportBatchItem item)? onUpdate,
  }) async {
    if (_running) throw StateError('photo batch already running');
    _assertOwner();
    _running = true;
    _stopRequested = false;
    try {
      for (final item in items) {
        if (_stopRequested) break;
        if (item.state == PhotoImportItemState.saved) continue;
        if (item.state != PhotoImportItemState.waiting &&
            item.state != PhotoImportItemState.failed) continue;
        _assertOwner();

        item.errorCode = null;
        item.state = PhotoImportItemState.uploading;
        onUpdate?.call(item);
        final e = item.selected.evidence;
        final mode = e.captureTimeUtc != null
            ? 'EXIF_ORIGINAL_OFFSET'
            : e.localCaptureTime != null
                ? 'EXIF_LOCAL_ONLY'
                : 'UNKNOWN';
        final provenance = <String, dynamic>{
          'selection_method': 'SYSTEM_PHOTO_PICKER',
          'capture_time_source': mode,
          if (e.localCaptureTime != null)
            'local_capture_time': e.localCaptureTime,
          if (e.utcOffsetMinutes != null)
            'utc_offset_minutes': e.utcOffsetMinutes,
          if (e.hasGps) 'gps_latitude': e.latitude,
          if (e.hasGps) 'gps_longitude': e.longitude,
        };

        try {
          // The picker may have copied into a cache path that is later rotated
          // or modified. Do not upload a different same-sized file as the one
          // whose metadata and SHA-256 the user reviewed.
          if (!await _verifySelection(item.selected)) {
            throw const FormatException('selected photo changed after preview');
          }
          _assertOwner();
          final pending = PendingMediaFile.fromPath(
            path: item.selected.path,
            clientUploadId: item.clientUploadId,
            contentType: item.selected.contentType,
            sizeBytes: item.selected.bytes,
            originalFilename: item.selected.originalFilename,
            // This timestamp is not transmitted for importer-sourced media.
            occurredAt: DateTime.now().toUtc(),
            ownsLocalFile: false,
          );
          final id = await _service.submitPhoto(
            pending,
            title: null,
            content: '',
            importProvenance: provenance,
            importCaptureUtc: e.captureTimeUtc,
            onPhase: (phase) {
              item.state = switch (phase) {
                MediaSubmissionPhase.uploading => PhotoImportItemState.uploading,
                MediaSubmissionPhase.verifying => PhotoImportItemState.verifying,
                MediaSubmissionPhase.saving => PhotoImportItemState.saving,
                MediaSubmissionPhase.transcribing => PhotoImportItemState.saving,
              };
              onUpdate?.call(item);
            },
          );
          _assertOwner();
          item.memoryId = id;
          item.state = PhotoImportItemState.saved;
          onUpdate?.call(item);
        } catch (error) {
          item.errorCode = error is ProtocolException
              ? 'SESSION_OR_PROTOCOL_CHANGED'
              : 'UPLOAD_OR_SAVE_FAILED';
          item.state = PhotoImportItemState.failed;
          onUpdate?.call(item);
          // An account switch is not an ordinary per-item failure. Stop the
          // old owner's remaining batch immediately; no cross-owner retries.
          _assertOwner();
        }
      }
    } finally {
      _running = false;
    }
  }
}
