import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/capture_media.dart';
import 'package:jiyidashi/photo_import_batch.dart';
import 'package:jiyidashi/photo_import_metadata.dart';
import 'package:jiyidashi/photo_import_journal.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

class _Api extends JiYiApiClient {
  _Api() : super(baseUrl: 'https://photo-import.invalid/v1') {
    authenticatedUserId = ownerA;
    accessToken = 'fixture';
  }
}

class _FakeSubmission extends TrustedMediaCaptureService {
  _FakeSubmission(super.api);

  final List<String> seenUploadIds = [];
  final List<Map<String, dynamic>> seenProvenance = [];
  final List<DateTime?> seenCaptureUtc = [];
  bool failFirst = false;
  void Function()? sideEffect;

  @override
  Future<String> submitPhoto(
    PendingMediaFile file, {
    String? title,
    required String content,
    Map<String, dynamic>? importProvenance,
    DateTime? importCaptureUtc,
    void Function(MediaSubmissionPhase phase)? onPhase,
  }) async {
    seenUploadIds.add(file.clientUploadId);
    seenProvenance.add(importProvenance ?? {});
    seenCaptureUtc.add(importCaptureUtc);
    onPhase?.call(MediaSubmissionPhase.uploading);
    if (failFirst && seenUploadIds.length == 1) {
      throw TransportException('temporary offline');
    }
    onPhase?.call(MediaSubmissionPhase.verifying);
    onPhase?.call(MediaSubmissionPhase.saving);
    sideEffect?.call();
    return 'memory-${file.clientUploadId}';
  }
}

class _PausedSubmission extends _FakeSubmission {
  _PausedSubmission(super.api);
  final Completer<void> entered = Completer<void>();
  final Completer<void> release = Completer<void>();

  @override
  Future<String> submitPhoto(
    PendingMediaFile file, {
    String? title,
    required String content,
    Map<String, dynamic>? importProvenance,
    DateTime? importCaptureUtc,
    void Function(MediaSubmissionPhase phase)? onPhase,
  }) async {
    seenUploadIds.add(file.clientUploadId);
    entered.complete();
    await release.future;
    return 'memory-${file.clientUploadId}';
  }
}

SelectedPhotoImport _photo(
  String hash, {
  PhotoCaptureEvidence evidence = const PhotoCaptureEvidence(),
}) => SelectedPhotoImport(
  path: '/not-opened/$hash.jpeg',
  originalFilename: '$hash.jpeg',
  bytes: 128,
  contentType: 'image/jpeg',
  contentSha256: hash,
  evidence: evidence,
);

PhotoImportSelection _selection(List<SelectedPhotoImport> selected) =>
    PhotoImportSelection(selected: selected, failedNames: const [], duplicates: 0);

void main() {
  test('batch is sequential and only submits selected assets', () async {
    final api = _Api();
    final service = _FakeSubmission(api);
    final batch = PhotoImportBatchCoordinator(
      api: api,
      service: service,
      verifySelection: (_) async => true,
      selection: _selection([_photo('1'), _photo('2')]),
    );
    final progress = <PhotoImportItemState>[];
    await batch.submit(onUpdate: (item) => progress.add(item.state));

    expect(service.seenUploadIds, hasLength(2));
    expect(service.seenUploadIds[0], isNot(service.seenUploadIds[1]));
    expect(batch.savedCount, 2);
    expect(batch.failedCount, 0);
    expect(progress, contains(PhotoImportItemState.verifying));
    expect(service.seenProvenance.every(
      (p) => p['capture_time_source'] == 'UNKNOWN' &&
          !p.containsKey('local_capture_time'),
    ), isTrue);
    expect(service.seenCaptureUtc, [null, null]);
  });

  test('changed selected asset is not uploaded after user reviewed metadata', () async {
    final api = _Api();
    final service = _FakeSubmission(api);
    final batch = PhotoImportBatchCoordinator(
      api: api,
      service: service,
      verifySelection: (_) async => false,
      selection: _selection([_photo('tampered')]),
    );
    await batch.submit();
    expect(batch.savedCount, 0);
    expect(batch.failedCount, 1);
    expect(service.seenUploadIds, isEmpty);
  });

  test('retry keeps immutable upload UUID after transient error', () async {
    final api = _Api();
    final service = _FakeSubmission(api)..failFirst = true;
    final batch = PhotoImportBatchCoordinator(
      api: api,
      service: service,
      verifySelection: (_) async => true,
      selection: _selection([_photo('A')]),
    );
    await batch.submit();
    expect(batch.failedCount, 1);
    await batch.submit();
    expect(batch.savedCount, 1);
    expect(service.seenUploadIds, hasLength(2));
    expect(service.seenUploadIds[0], service.seenUploadIds[1]);
    await batch.submit();
    expect(service.seenUploadIds, hasLength(2), reason: 'saved item never replayed');
  });

  test('explicit stop waits for in-flight commit and leaves later items waiting', () async {
    final api = _Api();
    final service = _FakeSubmission(api);
    final batch = PhotoImportBatchCoordinator(
      api: api,
      service: service,
      verifySelection: (_) async => true,
      selection: _selection([_photo('1'), _photo('2')]),
    );
    await batch.submit(onUpdate: (item) {
      if (item.state == PhotoImportItemState.saved) {
        batch.stopAfterCurrentFile();
      }
    });
    expect(batch.savedCount, 1);
    expect(batch.items.last.state, PhotoImportItemState.waiting);
    await batch.submit();
    expect(batch.savedCount, 2);
  });

  test('EXIF offset and GPS are clues; importer never submits picker timestamp', () async {
    final api = _Api();
    final service = _FakeSubmission(api);
    final captured = DateTime.utc(2025, 8, 8, 17, 15);
    final batch = PhotoImportBatchCoordinator(
      api: api,
      service: service,
      verifySelection: (_) async => true,
      selection: _selection([_photo('1', evidence: PhotoCaptureEvidence(
        localCaptureTime: '2025-08-09 01:15:00',
        captureTimeUtc: captured,
        utcOffsetMinutes: 480,
        latitude: 31.23,
        longitude: 121.47,
      ))]),
    );
    await batch.submit();
    expect(service.seenCaptureUtc.single, captured);
    expect(service.seenProvenance.single['capture_time_source'], 'EXIF_ORIGINAL_OFFSET');
    expect(service.seenProvenance.single['gps_latitude'], 31.23);
    expect(service.seenProvenance.single['gps_longitude'], 121.47);
  });

  test('account switch during first media operation never uploads the next owner item', () async {
    final api = _Api();
    final service = _FakeSubmission(api);
    service.sideEffect = () => api.authenticatedUserId = ownerB;
    final batch = PhotoImportBatchCoordinator(
      api: api,
      service: service,
      verifySelection: (_) async => true,
      selection: _selection([_photo('1'), _photo('2')]),
    );
    await expectLater(batch.submit(), throwsA(isA<ProtocolException>()));
    expect(service.seenUploadIds, hasLength(1));
    expect(batch.savedCount, 0);
    await expectLater(batch.submit(), throwsA(isA<ProtocolException>()));
    expect(service.seenUploadIds, hasLength(1));
  });
  group('authoritative completed-photo receipts', () {
    late Directory temp;
    late OfflineQueueStore store;
    late File source;
    late SelectedPhotoImport photo;
    late PhotoImportJournal journal;

    setUp(() async {
      sqfliteFfiInit();
      temp = await Directory.systemTemp.createTemp('jiyi-receipt-');
      source = File('${temp.path}${Platform.pathSeparator}selected.jpeg');
      await source.writeAsBytes([0xff, 0xd8, 0xff, ...List.filled(40, 0)]);
      photo = SelectedPhotoImport(
        path: source.path,
        originalFilename: 'selected.jpeg',
        bytes: 43,
        contentType: 'image/jpeg',
        contentSha256: sha256.convert(await source.readAsBytes()).toString(),
        evidence: const PhotoCaptureEvidence(),
      );
      store = OfflineQueueStore(
        factory: databaseFactoryFfiNoIsolate,
        databasePathProvider: () async =>
            '${temp.path}${Platform.pathSeparator}outbox.sqlite',
      );
      journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    });

    tearDown(() async {
      await store.close();
      await temp.delete(recursive: true);
    });

    Future<void> firstUpload(_Api api, _FakeSubmission service) async {
      final batch = PhotoImportBatchCoordinator(
        api: api,
        service: service,
        selection: _selection([photo]),
        journal: journal,
        verifySelection: (_) async => true,
      );
      await batch.submit();
      expect(batch.savedCount, 1);
      expect(service.seenUploadIds, hasLength(1));
    }

    test('batch retry rejects same-length staged tampering before media service', () async {
      final api = _Api();
      final service = _FakeSubmission(api)..failFirst = true;
      const uuid = '87654321-1234-4234-8234-123456789abc';
      final batch = PhotoImportBatchCoordinator.restored(
        api: api,
        journal: journal,
        service: service,
        restoredItems: [PhotoImportBatchItem(photo, clientUploadId: uuid)],
      );
      await batch.submit();
      expect(batch.failedCount, 1);
      expect(service.seenUploadIds, [uuid]);
      final failed = (await store.findByClientUuid(ownerA, uuid))!;
      expect(failed.status, OfflineQueueStatus.failed);
      final staged = await journal.selectedFrom(failed);
      final bytes = await File(staged.path).readAsBytes();
      bytes[bytes.length - 1] ^= 1;
      await File(staged.path).writeAsBytes(bytes, flush: true);
      expect(await File(staged.path).length(), photo.bytes);
      expect(await File(source.path).readAsBytes(), isNot(bytes));
      await batch.submit();
      expect(service.seenUploadIds, [uuid],
          reason: 'corrupt staged copy must never reach upload service');
      expect(batch.failedCount, 1);
      expect((await store.findByClientUuid(ownerA, uuid))!.status,
          OfflineQueueStatus.failed,
          reason: 'failed retry must remain available without stuck sending');
    });

    test('same-process reopening never reclaims a live sending UUID', () async {
      final api = _Api();
      final service = _PausedSubmission(api);
      const uuid = '12345678-1234-4234-8234-123456789abc';
      final original = PhotoImportBatchCoordinator.restored(
        api: api,
        journal: journal,
        service: service,
        verifySelection: (_) async => true,
        restoredItems: [PhotoImportBatchItem(photo, clientUploadId: uuid)],
      );
      final first = original.submit();
      await service.entered.future;
      final stored = (await store.findByClientUuid(ownerA, uuid))!;
      expect(stored.status, OfflineQueueStatus.sending);
      expect(PhotoImportBatchCoordinator.isUploadActive(ownerA, uuid), true);
      final reopened = PhotoImportBatchCoordinator.restored(
        api: api,
        journal: journal,
        service: service,
        verifySelection: (_) async => true,
        restoredItems: [PhotoImportBatchItem(
          await journal.selectedFrom(stored), clientUploadId: uuid,
        )],
      );
      await reopened.submit();
      expect(service.seenUploadIds, hasLength(1));
      expect((await store.findByClientUuid(ownerA, uuid))!.status,
          OfflineQueueStatus.sending);
      service.release.complete();
      await first;
      expect(service.seenUploadIds, hasLength(1));
      expect(PhotoImportBatchCoordinator.isUploadActive(ownerA, uuid), false);
    });

    test('deleted server memory does not produce false local success', () async {
      final api = _Api();
      final service = _FakeSubmission(api);
      await firstUpload(api, service);
      final old = (await journal.findSameContent(photo.contentSha256))!;
      final second = PhotoImportBatchCoordinator(
        api: api,
        selection: _selection([photo]),
        journal: journal,
        service: service,
        verifySelection: (_) async => true,
        readExistingMemory: (_) async => throw ApiException(404, 'MEMORY_NOT_FOUND'),
      );
      await second.submit();
      expect(second.savedCount, 1);
      expect(service.seenUploadIds, hasLength(2),
          reason: 'a deleted server Memory demands a new uploaded media UUID');
      expect(service.seenUploadIds[1], isNot(service.seenUploadIds.first));
      expect((await journal.findSameContent(photo.contentSha256))!.clientUuid,
          service.seenUploadIds.last);
      expect((await store.findByClientUuid(ownerA, old.clientUuid))!.status,
          OfflineQueueStatus.completed);
    });

    test('offline verification leaves completed receipt uncertain, not saved', () async {
      final api = _Api();
      final service = _FakeSubmission(api);
      await firstUpload(api, service);
      final second = PhotoImportBatchCoordinator(
        api: api,
        selection: _selection([photo]),
        journal: journal,
        service: service,
        verifySelection: (_) async => true,
        readExistingMemory: (_) async => throw TransportException('offline'),
      );
      await second.submit();
      expect(second.savedCount, 0);
      expect(second.failedCount, 1);
      expect(service.seenUploadIds, hasLength(1));
    });

    test('live owner-owned source receipt is reused only after server GET', () async {
      final api = _Api();
      final service = _FakeSubmission(api);
      await firstUpload(api, service);
      final previousId = 'memory-${service.seenUploadIds.first}';
      final second = PhotoImportBatchCoordinator(
        api: api,
        selection: _selection([photo]),
        journal: journal,
        service: service,
        verifySelection: (_) async => true,
        readExistingMemory: (id) async => {
          'id': id,
          'user_id': ownerA,
          'memory_type': 'PHOTO',
          'source_type': 'USER_PHOTO',
          'metadata_json': {'media_id': 'source-media-id'},
        },
      );
      await second.submit();
      expect(second.savedCount, 1);
      expect(second.items.single.memoryId, previousId);
      expect(service.seenUploadIds, hasLength(1));
    });

    test('different owner receipt can never be reused', () async {
      final api = _Api();
      final service = _FakeSubmission(api);
      await firstUpload(api, service);
      final second = PhotoImportBatchCoordinator(
        api: api,
        selection: _selection([photo]),
        journal: journal,
        service: service,
        verifySelection: (_) async => true,
        readExistingMemory: (id) async => {
          'id': id,
          'user_id': ownerB,
          'memory_type': 'PHOTO',
          'source_type': 'USER_PHOTO',
          'metadata_json': {'media_id': 'source-media-id'},
        },
      );
      await second.submit();
      expect(second.savedCount, 0);
      expect(service.seenUploadIds, hasLength(1));
      expect((await journal.findSameContent(photo.contentSha256))!.status,
          OfflineQueueStatus.completed);
    });
  });

}
