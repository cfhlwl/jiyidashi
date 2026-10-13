import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/photo_import_page.dart';
import 'package:jiyidashi/photo_import_batch.dart';
import 'package:jiyidashi/photo_import_journal.dart';
import 'package:jiyidashi/capture_media.dart';
import 'package:jiyidashi/photo_import_metadata.dart';

const ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const uploadId = 'c1c1c1c1-c1c1-41c1-81c1-c1c1c1c1c1c1';

class _Api extends JiYiApiClient {
  _Api(String owner) : super(baseUrl: 'https://photo-import-test.invalid/v1') {
    authenticatedUserId = owner;
    accessToken = 'test-token';
  }
}

/// UI contract fixture only. The true on-disk SQLite reopen, crash recovery,
/// SHA verification and owner purge are covered by photo_import_journal_test.
/// Running real sqflite_ffi file operations within testWidgets FakeAsync causes
/// the widget test to wait for IO that can never be dispatched (10m timeout).
class _OwnerScopedQueueFixture extends OfflineQueueStore {
  _OwnerScopedQueueFixture()
      : super(databasePathProvider: () async => '/fixture/unused.sqlite3');

  int listCalls = 0;
  OfflineQueueStatus rowStatus = OfflineQueueStatus.pending;

  @override
  bool get supportsPhotoImportFileSweep => false;

  @override
  Future<List<OfflineQueueItem>> listAll(String ownerUserId) async {
    listCalls++;
    if (ownerUserId != ownerA) {
      return const [];
    }
    final now = DateTime.utc(2026, 10, 13);
    return [
      OfflineQueueItem(
        id: 1,
        ownerUserId: ownerA,
        clientUuid: uploadId,
        operationType: OfflineQueueStore.photoImportOperation,
        payload: {
          'staged_path': '/fixture/photos/$ownerA/$uploadId.bin',
          'original_filename': 'restored.jpeg',
          'size_bytes': 23,
          'content_type': 'image/jpeg',
          'sha256': List.filled(64, 'a').join(),
          'evidence': <String, dynamic>{},
        },
        status: rowStatus,
        attemptCount: 0,
        retryable: true,
        createdAt: now,
        updatedAt: now,
      ),
    ];
  }

  @override
  Future<Directory> photoImportOwnerDirectory(String ownerUserId) async =>
      Directory('/fixture/photos/$ownerUserId');
}

class _DelayedQueue extends _OwnerScopedQueueFixture {
  final Completer<void> gate = Completer<void>();

  @override
  Future<List<OfflineQueueItem>> listAll(String ownerUserId) async {
    await gate.future;
    return super.listAll(ownerUserId);
  }
}

class _SelectionPicker extends PhotoImportPicker {
  @override
  Future<PhotoImportSelection> pick() async => PhotoImportSelection(
    selected: [
      SelectedPhotoImport(
        path: '/new-picker-photo.jpeg',
        originalFilename: 'new-picked.jpeg',
        bytes: 23,
        contentType: 'image/jpeg',
        contentSha256: List.filled(64, 'b').join(),
        evidence: const PhotoCaptureEvidence(),
      ),
    ],
    failedNames: const [],
    duplicates: 0,
  );
}

class _PausedMedia extends TrustedMediaCaptureService {
  _PausedMedia(super.api);
  final Completer<void> entered = Completer<void>();
  final Completer<void> release = Completer<void>();
  int attempts = 0;

  @override
  Future<String> submitPhoto(PendingMediaFile file, {
    String? title,
    required String content,
    Map<String, dynamic>? importProvenance,
    DateTime? importCaptureUtc,
    void Function(MediaSubmissionPhase phase)? onPhase,
  }) async {
    attempts++;
    entered.complete();
    await release.future;
    return 'memory-${file.clientUploadId}';
  }
}

class _LiveJournal extends PhotoImportJournal {
  _LiveJournal(_OwnerScopedQueueFixture queue)
      : _queue = queue, super(store: queue, ownerUserId: ownerA);
  final _OwnerScopedQueueFixture _queue;

  @override
  Future<OfflineQueueItem?> findSameContent(String sha256Hex) async => null;

  @override
  Future<OfflineQueueItem> stage(SelectedPhotoImport photo, {
    required String clientUploadId,
  }) async => (await _queue.listAll(ownerA)).single;

  @override
  Future<void> verifyStaged(OfflineQueueItem row) async {}

  @override
  Future<OfflineQueueItem> begin(OfflineQueueItem row) async => row;

  @override
  Future<OfflineQueueItem> complete(OfflineQueueItem row, {
    required String memoryId,
  }) async {
    _queue.rowStatus = OfflineQueueStatus.completed;
    return row;
  }
}

void main() {
  testWidgets('reopened page recognizes live upload and clears it after completion',
      (tester) async {
    final api = _Api(ownerA);
    final store = _OwnerScopedQueueFixture()..rowStatus = OfflineQueueStatus.sending;
    final media = _PausedMedia(api);
    final photo = SelectedPhotoImport(
      path: '/fixture/photos/$ownerA/$uploadId.bin',
      originalFilename: 'restored.jpeg',
      bytes: 23,
      contentType: 'image/jpeg',
      contentSha256: List.filled(64, 'a').join(),
      evidence: const PhotoCaptureEvidence(),
    );
    final original = PhotoImportBatchCoordinator.restored(
      api: api,
      journal: _LiveJournal(store),
      restoredItems: [PhotoImportBatchItem(photo, clientUploadId: uploadId)],
      service: media,
      verifySelection: (_) async => true,
    );
    final running = original.submit();
    await media.entered.future;
    expect(PhotoImportBatchCoordinator.isUploadActive(ownerA, uploadId), true);
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: api, offlineQueue: store,
    )));
    for (var i = 0; i < 12 &&
        find.textContaining('仍有照片正在上传').evaluate().isEmpty; i++) {
      await tester.pump();
    }
    expect(find.textContaining('仍有照片正在上传'), findsOneWidget);
    expect(find.textContaining('上传中'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('photo-import-submit')));
    await tester.pump();
    expect(media.attempts, 1, reason: 'reopened page must never start second upload');
    media.release.complete();
    await running;
    expect(store.rowStatus, OfflineQueueStatus.completed);
    await tester.pumpWidget(const MaterialApp(home: Scaffold()));
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: api, offlineQueue: store,
    )));
    for (var i = 0; i < 6; i++) { await tester.pump(); }
    expect(find.text('restored.jpeg'), findsNothing);
    expect(find.textContaining('仍有照片正在上传'), findsNothing);
    expect(media.attempts, 1);
  });


  testWidgets('delayed restore never overwrites newly chosen gallery batch',
      (tester) async {
    final store = _DelayedQueue();
    final api = _Api(ownerA);
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: api,
      offlineQueue: store,
      picker: _SelectionPicker(),
    )));
    await tester.tap(find.byKey(const ValueKey('photo-import-select')));
    await tester.pump();
    await tester.pump();
    expect(find.text('new-picked.jpeg'), findsOneWidget);
    store.gate.complete();
    for (var i = 0; i < 5; i++) {
      await tester.pump();
    }
    expect(find.text('new-picked.jpeg'), findsOneWidget);
    expect(find.text('restored.jpeg'), findsNothing);
    expect(find.textContaining('已恢复 1 张待续传照片'), findsNothing);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsOneWidget);
    api.authenticatedUserId = ownerB;
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: api, offlineQueue: store, picker: _SelectionPicker(),
    )));
    expect(find.text('new-picked.jpeg'), findsNothing);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsNothing);
  });

  testWidgets('restored gallery queue stays owner-scoped and never auto-uploads',
      (tester) async {
    final store = _OwnerScopedQueueFixture();

    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: _Api(ownerA),
      offlineQueue: store,
    )));
    // No real filesystem/SQLite work is performed by this widget contract:
    // the source directory is used for canonical path validation only.
    for (var i = 0; i < 8 &&
        find.textContaining('已恢复 1 张待续传照片').evaluate().isEmpty; i++) {
      await tester.pump();
    }
    expect(find.textContaining('已恢复 1 张待续传照片'), findsOneWidget);
    expect(find.text('restored.jpeg'), findsOneWidget);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsOneWidget);
    expect(store.listCalls, greaterThanOrEqualTo(1));
    expect(
      find.textContaining('已保存 1 张到当前账号'),
      findsNothing,
      reason: 'restoration must not claim server commit or upload without tap',
    );

    // Remount as owner B: the same persisted store must never show owner A's
    // filename, pending status, or submit action.
    await tester.pumpWidget(const MaterialApp(home: Scaffold()));
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: _Api(ownerB),
      offlineQueue: store,
    )));
    for (var i = 0; i < 4; i++) {
      await tester.pump();
    }
    expect(find.text('restored.jpeg'), findsNothing);
    expect(find.textContaining('已恢复 1 张待续传照片'), findsNothing);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsNothing);
  });
}
