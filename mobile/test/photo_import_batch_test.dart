import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/capture_media.dart';
import 'package:jiyidashi/photo_import_batch.dart';
import 'package:jiyidashi/photo_import_metadata.dart';

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

  test('retry keeps immutable upload UUID after transient error', () async {
    final api = _Api();
    final service = _FakeSubmission(api)..failFirst = true;
    final batch = PhotoImportBatchCoordinator(
      api: api,
      service: service,
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
      selection: _selection([_photo('1'), _photo('2')]),
    );
    await expectLater(batch.submit(), throwsA(isA<ProtocolException>()));
    expect(service.seenUploadIds, hasLength(1));
    expect(batch.savedCount, 0);
    await expectLater(batch.submit(), throwsA(isA<ProtocolException>()));
    expect(service.seenUploadIds, hasLength(1));
  });
}
