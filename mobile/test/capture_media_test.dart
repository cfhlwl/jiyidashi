import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/capture_media.dart';
import 'package:record/record.dart';

class _FakeMediaApi extends JiYiApiClient {
  _FakeMediaApi() : super(baseUrl: 'https://example.invalid/v1') {
    accessToken = 'media-token';
    authenticatedUserId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  }

  final calls = <String>[];
  bool alreadyReady = false;
  Object? signedPutError;
  Object? photoMemoryError;
  Object? voiceMemoryError;

  @override
  Future<MediaUploadSession> createMediaUpload({
    required String clientUploadId,
    required String kind,
    required String contentType,
    required int sizeBytes,
    String? originalFilename,
  }) async {
    calls.add('create:$kind:$clientUploadId:$contentType:$sizeBytes');
    return MediaUploadSession(
      mediaId: kind == 'IMAGE' ? 'photo-media' : 'voice-media',
      upload: alreadyReady
          ? null
          : SignedUploadTarget(
              method: 'PUT',
              url: Uri.parse('https://storage.invalid/upload'),
              headers: {'Content-Type': contentType},
            ),
    );
  }

  @override
  Future<void> uploadSignedMedia(SignedUploadTarget target, List<int> bytes) async {
    calls.add('put:${target.headers['Content-Type']}:${bytes.length}');
    final error = signedPutError;
    if (error != null) throw error;
  }

  @override
  Future<Map<String, dynamic>> completeMediaUpload(String mediaId) async {
    calls.add('complete:$mediaId');
    return {'id': mediaId, 'status': 'READY'};
  }

  @override
  Future<Map<String, dynamic>> createPhotoMemory({
    required String mediaId,
    String? title,
    required String content,
    DateTime? occurredAt,
  }) async {
    calls.add('photo-memory:$mediaId:$content');
    final error = photoMemoryError;
    if (error != null) throw error;
    return {'memory': {'id': 'photo-memory'}};
  }

  @override
  Future<Map<String, dynamic>> createVoiceMemory({
    required String mediaId,
    String? title,
    DateTime? occurredAt,
  }) async {
    calls.add('voice-memory:$mediaId');
    final error = voiceMemoryError;
    if (error != null) throw error;
    return {'memory': {'id': 'voice-memory'}};
  }
}

class _SessionSwitchMediaApi extends _FakeMediaApi {
  @override
  Future<MediaUploadSession> createMediaUpload({
    required String clientUploadId,
    required String kind,
    required String contentType,
    required int sizeBytes,
    String? originalFilename,
  }) async {
    final value = await super.createMediaUpload(
      clientUploadId: clientUploadId,
      kind: kind,
      contentType: contentType,
      sizeBytes: sizeBytes,
      originalFilename: originalFilename,
    );
    logout();
    accessToken = 'new-account-token';
    authenticatedUserId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
    return value;
  }
}

class _ResponseLossPhotoApi extends _FakeMediaApi {
  String? committedContent;

  @override
  Future<Map<String, dynamic>> createPhotoMemory({
    required String mediaId,
    String? title,
    required String content,
    DateTime? occurredAt,
  }) async {
    calls.add('photo-memory:$mediaId:$content');
    if (committedContent == null) {
      committedContent = content;
      throw TransportException('response lost after commit');
    }
    if (committedContent != content) {
      throw ApiException(409, 'MEDIA_MEMORY_IDEMPOTENCY_CONFLICT');
    }
    return {'memory': {'id': 'photo-memory'}};
  }
}

PendingMediaFile _memoryFile({
  required String id,
  required String contentType,
  required List<int> bytes,
}) {
  return PendingMediaFile(
    clientUploadId: id,
    contentType: contentType,
    sizeBytes: bytes.length,
    originalFilename: contentType.startsWith('image/') ? 'photo.jpg' : 'voice.m4a',
    occurredAt: DateTime.utc(2026, 9, 18),
    readBytes: () async => bytes,
  );
}

// [人工注释][S1-008] 直接控制 picker 返回文件，覆盖 Camera owned-cache 在建模前失败的清理语义。
class _SingleImagePicker extends ImagePicker {
  _SingleImagePicker(this.selected);

  final XFile? selected;

  @override
  Future<XFile?> pickImage({
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
    bool requestFullMetadata = true,
  }) async {
    return selected;
  }
}

// [人工注释][S1-008] 不触发原生 MethodChannel，精确制造 0-byte 与 stoppedPath 改写场景。
class _FakeCaptureAudioRecorder implements CaptureAudioRecorder {
  _FakeCaptureAudioRecorder({
    this.bytesOnStart = const [1],
    this.returnDifferentPath = false,
    this.startCompleter,
    this.startError,
    this.startRecordsBeforeError = false,
    this.stopError,
    this.cancelError,
    this.disposeError,
  });

  final List<int> bytesOnStart;
  final bool returnDifferentPath;
  final Completer<void>? startCompleter;
  final Object? startError;
  final bool startRecordsBeforeError;
  final Object? stopError;
  final Object? cancelError;
  final Object? disposeError;
  bool recording = false;
  int cancelCalls = 0;
  int disposeCalls = 0;
  String? startedPath;
  String? stoppedPath;

  @override
  Future<bool> isRecording() async => recording;

  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<void> start(RecordConfig config, {required String path}) async {
    startedPath = path;
    final delayed = startCompleter;
    if (delayed != null) await delayed.future;
    final error = startError;
    if (error != null) {
      if (startRecordsBeforeError) {
        recording = true;
        await File(path).writeAsBytes(bytesOnStart, flush: true);
      }
      throw error;
    }
    recording = true;
    await File(path).writeAsBytes(bytesOnStart, flush: true);
  }

  @override
  Future<String?> stop() async {
    final error = stopError;
    if (error != null) throw error;
    recording = false;
    if (!returnDifferentPath) return startedPath;
    final alternate = '${startedPath!}.stopped';
    await File(alternate).writeAsBytes(const [1], flush: true);
    stoppedPath = alternate;
    return alternate;
  }

  @override
  Future<void> cancel() async {
    cancelCalls += 1;
    final error = cancelError;
    if (error != null) throw error;
    recording = false;
  }

  @override
  Future<void> dispose() async {
    disposeCalls += 1;
    final error = disposeError;
    if (error != null) throw error;
    recording = false;
  }
}

void main() {
  test('camera validation failure deletes app-owned cache before PendingMediaFile exists',
      () async {
    final path = '${Directory.systemTemp.path}${Platform.pathSeparator}'
        'jiyidashi-camera-test-${newCaptureClientUuid()}.jpg';
    final file = File(path);
    await file.writeAsBytes('not-an-image'.codeUnits, flush: true);
    final device = PlatformCaptureMediaDevice(
      imagePicker: _SingleImagePicker(XFile(path, name: 'camera.jpg')),
    );

    // [人工注释][S1-008] Camera 文件属于应用；格式拒绝不能把原始 cache 留成孤儿。
    await expectLater(
      device.pickPhoto(fromCamera: true),
      throwsA(isA<CaptureMediaException>()),
    );
    expect(await file.exists(), isFalse);
    await device.dispose();
  });

  test('gallery validation failure never deletes the user-owned original',
      () async {
    final path = '${Directory.systemTemp.path}${Platform.pathSeparator}'
        'jiyidashi-gallery-test-${newCaptureClientUuid()}.jpg';
    final file = File(path);
    await file.writeAsBytes('not-an-image'.codeUnits, flush: true);
    final device = PlatformCaptureMediaDevice(
      imagePicker: _SingleImagePicker(XFile(path, name: 'gallery.jpg')),
    );

    await expectLater(
      device.pickPhoto(fromCamera: false),
      throwsA(isA<CaptureMediaException>()),
    );
    expect(await file.exists(), isTrue);
    await file.delete();
    await device.dispose();
  });

  test('partial native start failure confirms termination before clearing session',
      () async {
    final recorder = _FakeCaptureAudioRecorder(
      startError: StateError('method channel lost start response'),
      startRecordsBeforeError: true,
    );
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    // [人工注释][S1-008] 原生已开始但 start Future 抛错时，必须先 cancel 确认终止，再把原始 start 错误返回。
    await expectLater(
      device.startVoiceRecording(),
      throwsA(isA<StateError>()),
    );
    expect(recorder.cancelCalls, 1);
    expect(recorder.recording, isFalse);
    expect(await File(recorder.startedPath!).exists(), isFalse);
  });

  test('partial native start failure locks unknown when termination also fails',
      () async {
    final recorder = _FakeCaptureAudioRecorder(
      startError: StateError('method channel lost start response'),
      startRecordsBeforeError: true,
      cancelError: StateError('native cancel failed'),
      disposeError: StateError('native dispose failed'),
    );
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    await expectLater(
      device.startVoiceRecording(),
      throwsA(isA<RecorderTerminationUnknownException>()),
    );
    expect(recorder.recording, isTrue);
    expect(recorder.cancelCalls, 1);
    expect(recorder.disposeCalls, 1);

    // [人工注释][S1-008] session/unknown 状态必须阻止后续 start，不能把 start 异常当成“未录音”。
    await expectLater(
      device.startVoiceRecording(),
      throwsA(isA<RecorderTerminationUnknownException>()),
    );
  });

  test('stop failure locks unknown when stop cancel and hard dispose all fail',
      () async {
    final recorder = _FakeCaptureAudioRecorder(
      stopError: StateError('native stop failed'),
      cancelError: StateError('native cancel failed'),
      disposeError: StateError('native dispose failed'),
    );
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    expect(await device.startVoiceRecording(), isTrue);
    await expectLater(
      device.stopVoiceRecording(),
      throwsA(isA<RecorderTerminationUnknownException>()),
    );
    expect(recorder.recording, isTrue);
    expect(recorder.cancelCalls, 1);
    expect(recorder.disposeCalls, 1);
    await expectLater(
      device.startVoiceRecording(),
      throwsA(isA<RecorderTerminationUnknownException>()),
    );
  });

  test('cancel failure falls back to hard dispose before session is cleared',
      () async {
    final recorder = _FakeCaptureAudioRecorder(
      cancelError: StateError('native cancel failed'),
    );
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    expect(await device.startVoiceRecording(), isTrue);
    final path = recorder.startedPath!;
    expect(recorder.recording, isTrue);

    // [人工注释][S1-008] cancel 抛错不能清 session 后假装成功；hard dispose 成功才算确认终止。
    await device.cancelVoiceRecording();
    expect(recorder.cancelCalls, 1);
    expect(recorder.disposeCalls, 1);
    expect(recorder.recording, isFalse);
    expect(await File(path).exists(), isFalse);
    await expectLater(
      device.startVoiceRecording(),
      throwsA(isA<CaptureMediaException>()),
    );
  });

  test('cancel and hard dispose failure locks the device instead of faking stop',
      () async {
    final recorder = _FakeCaptureAudioRecorder(
      cancelError: StateError('native cancel failed'),
      disposeError: StateError('native dispose failed'),
    );
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    expect(await device.startVoiceRecording(), isTrue);
    await expectLater(
      device.cancelVoiceRecording(),
      throwsA(isA<CaptureMediaException>()),
    );
    expect(recorder.recording, isTrue);
    await expectLater(
      device.startVoiceRecording(),
      throwsA(isA<CaptureMediaException>()),
    );
  });

  test('dispose requested during start terminates a late native success',
      () async {
    final startCompleter = Completer<void>();
    final recorder = _FakeCaptureAudioRecorder(startCompleter: startCompleter);
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    final startFuture = device.startVoiceRecording();
    await Future<void>.delayed(Duration.zero);
    expect(recorder.startedPath, isNotNull);

    final disposeFuture = device.dispose();
    startCompleter.complete();

    await expectLater(startFuture, throwsA(isA<CaptureMediaException>()));
    await disposeFuture;

    // [人工注释][S1-008] dispose 先置门禁；late start 必须在 start Future 返回前被 cancel，不能留下后台录音。
    expect(recorder.cancelCalls, 1);
    expect(recorder.recording, isFalse);
    expect(recorder.disposeCalls, greaterThanOrEqualTo(1));
    expect(await File(recorder.startedPath!).exists(), isFalse);
  });

  test('zero-byte stopped recording is deleted instead of becoming an orphan',
      () async {
    final recorder = _FakeCaptureAudioRecorder(bytesOnStart: const []);
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    expect(await device.startVoiceRecording(), isTrue);
    final path = recorder.startedPath!;
    expect(await File(path).exists(), isTrue);

    // [人工注释][S1-008] stop 成功但本地文件无效时，必须在抛错前清理本次 app-owned temp。
    await expectLater(
      device.stopVoiceRecording(),
      throwsA(isA<CaptureMediaException>()),
    );
    expect(await File(path).exists(), isFalse);
    await device.dispose();
  });

  test('recorder alternate stop path does not leave the expected temp behind',
      () async {
    final recorder = _FakeCaptureAudioRecorder(returnDifferentPath: true);
    final device = PlatformCaptureMediaDevice(recorder: recorder);

    expect(await device.startVoiceRecording(), isTrue);
    final expectedPath = recorder.startedPath!;
    final clip = await device.stopVoiceRecording();
    final alternatePath = recorder.stoppedPath!;

    expect(clip, isNotNull);
    expect(clip!.localPath, alternatePath);
    expect(await File(expectedPath).exists(), isFalse);
    expect(await File(alternatePath).exists(), isTrue);
    await device.deleteOwnedFile(clip);
    expect(await File(alternatePath).exists(), isFalse);
    await device.dispose();
  });

  test('detects supported image signatures without trusting file extension', () {
    expect(detectImageContentTypeFromPrefix([0xff, 0xd8, 0xff, 0xe0]), 'image/jpeg');
    expect(
      detectImageContentTypeFromPrefix(
        [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
      ),
      'image/png',
    );
    expect(detectImageContentTypeFromPrefix('not-image'.codeUnits), isNull);
  });

  test('photo follows signed upload -> READY -> Evidence memory once', () async {
    final api = _FakeMediaApi();
    final service = TrustedMediaCaptureService(api);
    final file = _memoryFile(
      id: '11111111-1111-4111-8111-111111111111',
      contentType: 'image/jpeg',
      bytes: [0xff, 0xd8, 0xff],
    );
    final phases = <MediaSubmissionPhase>[];
    final memoryId = await service.submitPhoto(
      file,
      content: '酒店发票',
      onPhase: phases.add,
    );
    expect(memoryId, 'photo-memory');
    expect(phases, [
      MediaSubmissionPhase.uploading,
      MediaSubmissionPhase.verifying,
      MediaSubmissionPhase.saving,
    ]);
    expect(api.calls, [
      'create:IMAGE:11111111-1111-4111-8111-111111111111:image/jpeg:3',
      'put:image/jpeg:3',
      'complete:photo-media',
      'photo-memory:photo-media:酒店发票',
    ]);
  });

  test('voice reuses the same client id and reaches server ASR path', () async {
    final api = _FakeMediaApi();
    final service = TrustedMediaCaptureService(api);
    final file = _memoryFile(
      id: '22222222-2222-4222-8222-222222222222',
      contentType: 'audio/mp4',
      bytes: [0, 0, 0, 16, 0x66, 0x74, 0x79, 0x70],
    );
    final phases = <MediaSubmissionPhase>[];
    final memoryId = await service.submitVoice(file, onPhase: phases.add);
    expect(memoryId, 'voice-memory');
    expect(phases, [
      MediaSubmissionPhase.uploading,
      MediaSubmissionPhase.verifying,
      MediaSubmissionPhase.transcribing,
    ]);
    expect(
      api.calls.first,
      'create:AUDIO:22222222-2222-4222-8222-222222222222:audio/mp4:8',
    );
    expect(api.calls.last, 'voice-memory:voice-media');
  });

  test('READY retry skips re-upload and never reloads local bytes', () async {
    final api = _FakeMediaApi()..alreadyReady = true;
    final service = TrustedMediaCaptureService(api);
    final file = PendingMediaFile(
      clientUploadId: '33333333-3333-4333-8333-333333333333',
      contentType: 'image/jpeg',
      sizeBytes: 3,
      originalFilename: 'photo.jpg',
      occurredAt: DateTime.utc(2026, 9, 18),
      readBytes: () => throw StateError('READY retry must not read the file'),
    );
    final memoryId = await service.submitPhoto(file, content: '安全重试');
    expect(memoryId, 'photo-memory');
    expect(api.calls.where((call) => call.startsWith('put:')), isEmpty);
  });

  test('signed PUT failure stops before READY and memory creation', () async {
    final api = _FakeMediaApi()
      ..signedPutError = TransportException('storage unavailable');
    final service = TrustedMediaCaptureService(api);
    final file = _memoryFile(
      id: '77777777-7777-4777-8777-777777777777',
      contentType: 'image/jpeg',
      bytes: [0xff, 0xd8, 0xff],
    );

    await expectLater(
      service.submitPhoto(file, content: 'PUT 失败'),
      throwsA(isA<TransportException>()),
    );
    expect(api.calls.where((call) => call.startsWith('complete:')), isEmpty);
    expect(api.calls.where((call) => call.startsWith('photo-memory:')), isEmpty);
  });

  test('photo memory endpoint failure never becomes local success', () async {
    final api = _FakeMediaApi()
      ..photoMemoryError = ApiException(503, 'photo endpoint failed');
    final service = TrustedMediaCaptureService(api);
    final file = _memoryFile(
      id: '88888888-8888-4888-8888-888888888888',
      contentType: 'image/jpeg',
      bytes: [0xff, 0xd8, 0xff],
    );

    await expectLater(
      service.submitPhoto(file, content: 'Photo endpoint 失败'),
      throwsA(isA<ApiException>()),
    );
  });

  test('voice ASR endpoint failure never becomes local success', () async {
    final api = _FakeMediaApi()
      ..voiceMemoryError = ApiException(504, 'ASR_TIMEOUT');
    final service = TrustedMediaCaptureService(api);
    final file = _memoryFile(
      id: '99999999-9999-4999-8999-999999999999',
      contentType: 'audio/mp4',
      bytes: [0, 0, 0, 16, 0x66, 0x74, 0x79, 0x70],
    );

    await expectLater(
      service.submitVoice(file),
      throwsA(isA<ApiException>()),
    );
  });

  test('response loss followed by changed photo payload is rejected', () async {
    final api = _ResponseLossPhotoApi()..alreadyReady = true;
    final service = TrustedMediaCaptureService(api);
    final file = _memoryFile(
      id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      contentType: 'image/jpeg',
      bytes: [0xff, 0xd8, 0xff],
    );

    await expectLater(
      service.submitPhoto(file, content: '内容 A'),
      throwsA(isA<TransportException>()),
    );
    expect(api.committedContent, '内容 A');

    await expectLater(
      service.submitPhoto(file, content: '内容 B'),
      throwsA(
        isA<ApiException>().having(
          (error) => error.message,
          'message',
          'MEDIA_MEMORY_IDEMPOTENCY_CONFLICT',
        ),
      ),
    );
    expect(
      api.calls.where((call) => call.startsWith('create:IMAGE:')).length,
      2,
    );
  });
}


test('trusted voice capture stops before storage after account switch', () async {
  final api = _SessionSwitchMediaApi();
  final service = TrustedMediaCaptureService(api);
  final file = _memoryFile(
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    contentType: 'audio/mp4',
    bytes: [0, 0, 0, 16, 0x66, 0x74, 0x79, 0x70],
  );

  await expectLater(
    service.submitVoice(file),
    throwsA(isA<ProtocolException>()),
  );

  expect(api.calls.where((call) => call.startsWith('put:')), isEmpty);
  expect(api.calls.where((call) => call.startsWith('complete:')), isEmpty);
  expect(api.calls.where((call) => call.startsWith('voice-memory:')), isEmpty);
})
