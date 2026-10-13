import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/photo_import_page.dart';
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
        status: OfflineQueueStatus.pending,
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

void main() {
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
