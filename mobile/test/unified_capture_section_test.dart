import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/capture_media.dart';
import 'package:jiyidashi/unified_capture_section.dart';
import 'package:record/record.dart';

class _WidgetMediaApi extends JiYiApiClient {
  _WidgetMediaApi() : super(baseUrl: 'https://example.invalid/v1') {
    accessToken = 'widget-token';
    authenticatedUserId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  }
  int mediaCreates = 0;
  int signedPuts = 0;
  int mediaCompletes = 0;
  int photoMemories = 0;
  int voiceMemories = 0;

  @override
  Future<MediaUploadSession> createMediaUpload({
    required String clientUploadId,
    required String kind,
    required String contentType,
    required int sizeBytes,
    String? originalFilename,
  }) async {
    mediaCreates += 1;
    return MediaUploadSession(
      mediaId: 'media-1',
      upload: SignedUploadTarget(
        method: 'PUT',
        url: Uri.parse('https://storage.invalid/upload'),
        headers: {'Content-Type': contentType},
      ),
    );
  }

  @override
  Future<void> uploadSignedMedia(
    SignedUploadTarget target,
    List<int> bytes,
  ) async {
    signedPuts += 1;
  }

  @override
  Future<Map<String, dynamic>> completeMediaUpload(String mediaId) async {
    mediaCompletes += 1;
    return {'id': mediaId, 'status': 'READY'};
  }

  @override
  Future<Map<String, dynamic>> createPhotoMemory({
    required String mediaId,
    String? title,
    required String content,
    DateTime? occurredAt,
  }) async {
    photoMemories += 1;
    return {'memory': {'id': 'memory-photo'}};
  }

  @override
  Future<Map<String, dynamic>> createVoiceMemory({
    required String mediaId,
    String? title,
    DateTime? occurredAt,
  }) async {
    voiceMemories += 1;
    return {'memory': {'id': 'memory-voice'}};
  }
}

class _ResponseLossWidgetMediaApi extends _WidgetMediaApi {
  String? committedContent;

  @override
  Future<Map<String, dynamic>> createPhotoMemory({
    required String mediaId,
    String? title,
    required String content,
    DateTime? occurredAt,
  }) async {
    if (committedContent == null) {
      committedContent = content;
      photoMemories += 1;
      throw TransportException('response lost after commit');
    }
    if (committedContent != content) {
      throw ApiException(409, 'MEDIA_MEMORY_IDEMPOTENCY_CONFLICT');
    }
    return {'memory': {'id': 'memory-photo'}};
  }
}

class _FailingVoiceMemoryApi extends _WidgetMediaApi {
  @override
  Future<Map<String, dynamic>> createVoiceMemory({
    required String mediaId,
    String? title,
    DateTime? occurredAt,
  }) async {
    throw ApiException(504, 'ASR_TIMEOUT');
  }
}

class _FailingCompleteMediaApi extends _WidgetMediaApi {
  @override
  Future<Map<String, dynamic>> completeMediaUpload(String mediaId) async {
    throw ApiException(503, '服务暂时不可用');
  }
}

class _WidgetMediaDevice implements CaptureMediaDevice {
  _WidgetMediaDevice({
    this.voicePermission = false,
    this.deleteFailuresRemaining = 0,
    this.recoveredPhoto,
    this.photoCompleter,
    this.startCompleter,
    this.startError,
    this.stopCompleter,
    this.cancelError,
  });
  final bool voicePermission;
  int deleteFailuresRemaining;
  final PendingMediaFile? recoveredPhoto;
  final Completer<PendingMediaFile?>? photoCompleter;
  final Completer<bool>? startCompleter;
  final Object? startError;
  final Completer<PendingMediaFile?>? stopCompleter;
  final Object? cancelError;
  bool recording = false;
  int deleteCalls = 0;
  int cancelCalls = 0;
  int startCalls = 0;

  @override
  Future<PendingMediaFile?> pickPhoto({required bool fromCamera}) async {
    final delayed = photoCompleter;
    if (delayed != null) return delayed.future;
    return PendingMediaFile(
      clientUploadId: '44444444-4444-4444-8444-444444444444',
      contentType: 'image/jpeg',
      sizeBytes: 3,
      originalFilename: 'picked.jpg',
      occurredAt: DateTime.utc(2026, 9, 18),
      ownsLocalFile: fromCamera,
      readBytes: () async => [0xff, 0xd8, 0xff],
    );
  }

  @override
  Future<PendingMediaFile?> recoverLostPhoto() async => recoveredPhoto;

  @override
  Future<bool> startVoiceRecording() async {
    startCalls += 1;
    final delayed = startCompleter;
    final allowed = delayed == null ? voicePermission : await delayed.future;
    final error = startError;
    if (error != null) {
      recording = error is RecorderTerminationUnknownException;
      throw error;
    }
    recording = allowed;
    return allowed;
  }

  @override
  Future<PendingMediaFile?> stopVoiceRecording() async {
    if (!recording) return null;
    final delayed = stopCompleter;
    if (delayed != null) {
      final clip = await delayed.future;
      recording = false;
      return clip;
    }
    recording = false;
    return PendingMediaFile(
      clientUploadId: '55555555-5555-4555-8555-555555555555',
      contentType: 'audio/mp4',
      sizeBytes: 8,
      originalFilename: 'voice.m4a',
      occurredAt: DateTime.utc(2026, 9, 18),
      ownsLocalFile: true,
      readBytes: () async => [0, 0, 0, 16, 0x66, 0x74, 0x79, 0x70],
    );
  }
  @override
  Future<void> cancelVoiceRecording() async {
    cancelCalls += 1;
    final error = cancelError;
    if (error != null) throw error;
    recording = false;
  }
  @override
  Future<void> deleteOwnedFile(PendingMediaFile file) async {
    if (!file.ownsLocalFile) return;
    deleteCalls += 1;
    if (deleteFailuresRemaining > 0) {
      deleteFailuresRemaining -= 1;
      throw StateError('delete failed');
    }
  }
  @override
  Future<void> dispose() async {}
}

class _FakeWidgetAudioRecorder implements CaptureAudioRecorder {
  _FakeWidgetAudioRecorder(
    this.startCompleter, {
    this.stopError,
    this.cancelError,
    this.disposeError,
  });

  final Completer<void> startCompleter;
  final Object? stopError;
  final Object? cancelError;
  final Object? disposeError;
  bool recording = false;
  int cancelCalls = 0;
  int disposeCalls = 0;
  String? startedPath;

  @override
  Future<bool> isRecording() async => recording;

  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<void> start(RecordConfig config, {required String path}) async {
    startedPath = path;
    await startCompleter.future;
    recording = true;
  }

  @override
  Future<String?> stop() async {
    final error = stopError;
    if (error != null) throw error;
    recording = false;
    return startedPath;
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
  Future<void> pumpSection(
    WidgetTester tester,
    JiYiApiClient api,
    CaptureMediaDevice device, {
    bool elderMode = false,
  }) async {
    // [人工注释][S1-008] 每个 widget case 从前台开始，避免上一条生命周期测试污染后续 observer 初始态。
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: UnifiedMediaCaptureSection(
              api: api,
              mediaDevice: device,
              elderMode: elderMode,
            ),
          ),
        ),
      ),
    );
  }

  testWidgets('camera picker result returned after dispose is still cleaned',
      (tester) async {
    final api = _WidgetMediaApi();
    final photoCompleter = Completer<PendingMediaFile?>();
    final device = _WidgetMediaDevice(photoCompleter: photoCompleter);
    await pumpSection(tester, api, device);

    await tester.tap(find.byKey(const ValueKey('capture-photo-camera')));
    await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
    photoCompleter.complete(
      PendingMediaFile(
        clientUploadId: 'abababab-abab-4bab-8bab-abababababab',
        contentType: 'image/jpeg',
        sizeBytes: 3,
        originalFilename: 'late-camera.jpg',
        occurredAt: DateTime.utc(2026, 9, 18),
        ownsLocalFile: true,
        readBytes: () async => [0xff, 0xd8, 0xff],
      ),
    );
    await tester.pump();

    // [人工注释][S1-008] !mounted 不能直接 return，否则 camera cache 会失去最后一个 owner。
    expect(device.deleteCalls, 1);
    expect(api.photoMemories, 0);
  });

  testWidgets('photo capture reaches the verified media service path', (tester) async {
    final api = _WidgetMediaApi();
    await pumpSection(tester, api, _WidgetMediaDevice());
    await tester.tap(find.byKey(const ValueKey('capture-photo-gallery')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('capture-photo-content')),
      '这是需要报销的酒店发票',
    );
    await tester.tap(find.byKey(const ValueKey('capture-photo-submit')));
    await tester.tap(find.byKey(const ValueKey('capture-photo-submit')));
    await tester.pumpAndSettle();
    expect(api.photoMemories, 1);
    expect(find.textContaining('图片已验证并保存为可信记忆'), findsOneWidget);
  });

  testWidgets('camera cache photo is deleted after trusted success', (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice();
    await pumpSection(tester, api, device);

    await tester.tap(find.byKey(const ValueKey('capture-photo-camera')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('capture-photo-content')),
      '相机缓存清理测试',
    );
    await tester.tap(find.byKey(const ValueKey('capture-photo-submit')));
    await tester.pumpAndSettle();

    expect(api.photoMemories, 1);
    expect(device.deleteCalls, 1);
    expect(find.byKey(const ValueKey('capture-photo-submit')), findsNothing);
  });

  testWidgets('discarding a camera photo clears cache without creating memory',
      (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice();
    await pumpSection(tester, api, device);

    await tester.tap(find.byKey(const ValueKey('capture-photo-camera')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('capture-photo-clear')));
    await tester.pumpAndSettle();

    expect(device.deleteCalls, 1);
    expect(api.photoMemories, 0);
    expect(find.textContaining('图片已丢弃'), findsOneWidget);
  });

  testWidgets('lost picker result is restored without fake success', (tester) async {
    final recovered = PendingMediaFile(
      clientUploadId: '66666666-6666-4666-8666-666666666666',
      contentType: 'image/jpeg',
      sizeBytes: 3,
      originalFilename: 'recovered.jpg',
      occurredAt: DateTime.utc(2026, 9, 18),
      readBytes: () async => [0xff, 0xd8, 0xff],
    );
    final api = _WidgetMediaApi();
    await pumpSection(tester, api, _WidgetMediaDevice(recoveredPhoto: recovered));
    await tester.pumpAndSettle();

    expect(find.textContaining('已恢复上次未完成的图片选择'), findsOneWidget);
    expect(find.byKey(const ValueKey('capture-photo-submit')), findsOneWidget);
    expect(find.textContaining('保存为可信记忆'), findsNothing);
  });

  testWidgets('replacing a camera photo deletes the previous cache file',
      (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice();
    await pumpSection(tester, api, device);

    await tester.tap(find.byKey(const ValueKey('capture-photo-camera')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('capture-photo-camera')));
    await tester.pumpAndSettle();

    expect(device.deleteCalls, 1);
    expect(find.byKey(const ValueKey('capture-photo-submit')), findsOneWidget);
  });

  testWidgets('leaving the page best-effort deletes owned camera cache',
      (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice();
    await pumpSection(tester, api, device);

    await tester.tap(find.byKey(const ValueKey('capture-photo-camera')));
    await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();

    expect(device.deleteCalls, 1);
  });

  testWidgets('response loss then edited photo payload never renders fake success',
      (tester) async {
    final api = _ResponseLossWidgetMediaApi();
    await pumpSection(tester, api, _WidgetMediaDevice());

    await tester.tap(find.byKey(const ValueKey('capture-photo-gallery')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('capture-photo-content')),
      '内容 A',
    );
    await tester.tap(find.byKey(const ValueKey('capture-photo-submit')));
    await tester.pumpAndSettle();

    expect(api.photoMemories, 1);
    expect(find.textContaining('response lost after commit'), findsOneWidget);
    expect(find.textContaining('保存为可信记忆'), findsNothing);

    await tester.enterText(
      find.byKey(const ValueKey('capture-photo-content')),
      '内容 B',
    );
    await tester.tap(find.byKey(const ValueKey('capture-photo-submit')));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('服务器已经保存了这个媒体的另一版内容'),
      findsOneWidget,
    );
    expect(find.textContaining('✓ 图片已验证并保存为可信记忆'), findsNothing);
  });

  testWidgets('active recording is cancelled when app leaves foreground',
      (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice(voicePermission: true);
    await pumpSection(tester, api, device);

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    expect(device.recording, isTrue);

    // [人工注释][S1-008] paused 是隐私硬门禁：取消原生录音，不生成 clip，也不触发任何上传/ASR/Memory。
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    await tester.pump();

    expect(device.cancelCalls, 1);
    expect(device.recording, isFalse);
    expect(api.mediaCreates, 0);
    expect(api.signedPuts, 0);
    expect(api.mediaCompletes, 0);
    expect(api.voiceMemories, 0);
    expect(find.byKey(const ValueKey('capture-voice-submit')), findsNothing);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(device.startCalls, 1);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsOneWidget);
  });

  testWidgets('cancel failure keeps recording state locked after backgrounding',
      (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice(
      voicePermission: true,
      cancelError: StateError('cancel failed'),
    );
    await pumpSection(tester, api, device);

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    expect(device.recording, isTrue);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    await tester.pump();

    // [人工注释][S1-008] 无法确认终止时 UI 不能伪装成 stopped，也不能重新开放“开始录音”入口。
    expect(device.cancelCalls, 1);
    expect(device.recording, isTrue);
    expect(api.mediaCreates, 0);
    expect(api.voiceMemories, 0);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsNothing);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(find.byKey(const ValueKey('capture-voice-stop')), findsOneWidget);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsNothing);
  });

  testWidgets('start termination unknown keeps Stop and never exposes Start',
      (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice(
      startError: RecorderTerminationUnknownException(
        '无法确认录音已经停止。为保护隐私，当前录音入口已锁定，请关闭应用后重试。',
      ),
    );
    await pumpSection(tester, api, device);

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    await tester.pump();

    // [人工注释][S1-008] start 异常若明确为 terminationUnknown，UI 必须按“仍可能在录音”处理。
    expect(device.recording, isTrue);
    expect(find.byKey(const ValueKey('capture-voice-stop')), findsOneWidget);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsNothing);
    expect(api.mediaCreates, 0);
    expect(api.voiceMemories, 0);
  });

  testWidgets('recording start race is cancelled if app pauses during await',
      (tester) async {
    final api = _WidgetMediaApi();
    final startCompleter = Completer<bool>();
    final device = _WidgetMediaDevice(startCompleter: startCompleter);
    await pumpSection(tester, api, device);

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    expect(device.startCalls, 1);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    startCompleter.complete(true);
    await tester.pump();
    await tester.pump();

    // [人工注释][S1-008] start future 即使晚到成功，也只能进入 cancel，不能恢复 recording 或生成 voice clip。
    expect(device.cancelCalls, 1);
    expect(device.recording, isFalse);
    expect(api.mediaCreates, 0);
    expect(api.signedPuts, 0);
    expect(api.mediaCompletes, 0);
    expect(api.voiceMemories, 0);
    expect(find.byKey(const ValueKey('capture-voice-submit')), findsNothing);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(device.startCalls, 1);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsOneWidget);
  });

  testWidgets('stop termination unknown keeps Stop and never exposes Start',
      (tester) async {
    final api = _WidgetMediaApi();
    final started = Completer<void>()..complete();
    final recorder = _FakeWidgetAudioRecorder(
      started,
      stopError: StateError('native stop failed'),
      cancelError: StateError('native cancel failed'),
      disposeError: StateError('native dispose failed'),
    );
    final platformDevice = PlatformCaptureMediaDevice(recorder: recorder);
    await pumpSection(tester, api, platformDevice);

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    expect(recorder.recording, isTrue);

    await tester.tap(find.byKey(const ValueKey('capture-voice-stop')));
    await tester.pump();
    await tester.pump();

    // [人工注释][S1-008] stop->cancel->dispose 全失败时，device 抛 terminationUnknown，
    // UI 必须继续保留 Stop；Start 不得重新出现。
    expect(recorder.recording, isTrue);
    expect(recorder.cancelCalls, 1);
    expect(recorder.disposeCalls, 1);
    expect(find.byKey(const ValueKey('capture-voice-stop')), findsOneWidget);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsNothing);
    expect(api.mediaCreates, 0);
    expect(api.signedPuts, 0);
    expect(api.mediaCompletes, 0);
    expect(api.voiceMemories, 0);
  });

  testWidgets('stop result is discarded if app pauses while stop is awaiting',
      (tester) async {
    final api = _WidgetMediaApi();
    final stopCompleter = Completer<PendingMediaFile?>();
    final device = _WidgetMediaDevice(
      voicePermission: true,
      stopCompleter: stopCompleter,
    );
    await pumpSection(tester, api, device);

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('capture-voice-stop')));
    await tester.pump();

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    stopCompleter.complete(
      PendingMediaFile(
        clientUploadId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        contentType: 'audio/mp4',
        sizeBytes: 8,
        originalFilename: 'late-stop.m4a',
        occurredAt: DateTime.utc(2026, 9, 18),
        ownsLocalFile: true,
        readBytes: () async => [0, 0, 0, 16, 0x66, 0x74, 0x79, 0x70],
      ),
    );
    await tester.pump();
    await tester.pump();

    // [人工注释][S1-008] stop Future 晚到的 clip 只能删除，不能进入 submit/ASR/Memory。
    expect(device.deleteCalls, 1);
    expect(api.mediaCreates, 0);
    expect(api.signedPuts, 0);
    expect(api.mediaCompletes, 0);
    expect(api.voiceMemories, 0);
    expect(find.byKey(const ValueKey('capture-voice-submit')), findsNothing);
  });

  testWidgets('owned device dispose closes a start-in-flight late success',
      (tester) async {
    final api = _WidgetMediaApi();
    final startCompleter = Completer<void>();
    final recorder = _FakeWidgetAudioRecorder(startCompleter);
    final platformDevice = PlatformCaptureMediaDevice(recorder: recorder);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: UnifiedMediaCaptureSection(
            api: api,
            mediaDeviceFactory: () => platformDevice,
          ),
        ),
      ),
    );

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    expect(recorder.startedPath, isNotNull);

    // Widget 自己拥有 device；dispose 必须先打 device 门禁，再允许 native start 晚到。
    await tester.pumpWidget(const SizedBox.shrink());
    startCompleter.complete();
    await tester.pump();
    await tester.pump();

    expect(recorder.cancelCalls, 1);
    expect(recorder.recording, isFalse);
    expect(api.mediaCreates, 0);
    expect(api.voiceMemories, 0);
  });

  testWidgets(
      'server voice success stays success when local temp cleanup fails',
      (tester) async {
    final api = _WidgetMediaApi();
    final device = _WidgetMediaDevice(
      voicePermission: true,
      deleteFailuresRemaining: 1,
    );
    await pumpSection(tester, api, device);

    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('capture-voice-stop')));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-submit')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-submit')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-submit')));
    await tester.pumpAndSettle();

    expect(api.voiceMemories, 1);
    expect(find.textContaining('保存为可信记忆'), findsOneWidget);
    expect(find.textContaining('本地临时录音清理失败'), findsOneWidget);
    expect(find.textContaining('语音记录失败'), findsNothing);
    expect(find.byKey(const ValueKey('capture-voice-submit')), findsNothing);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsNothing);
    expect(
      find.widgetWithText(OutlinedButton, '再次清除本地临时录音'),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const ValueKey('capture-voice-clear')));
    await tester.pumpAndSettle();
    expect(find.textContaining('已经保存的记忆不受影响'), findsOneWidget);
    expect(find.byKey(const ValueKey('capture-voice-start')), findsOneWidget);
  });

  testWidgets('media completion failure never renders trusted success', (tester) async {
    final api = _FailingCompleteMediaApi();
    await pumpSection(tester, api, _WidgetMediaDevice());

    await tester.tap(find.byKey(const ValueKey('capture-photo-gallery')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('capture-photo-content')),
      '失败路径测试',
    );
    await tester.tap(find.byKey(const ValueKey('capture-photo-submit')));
    await tester.pumpAndSettle();

    expect(find.textContaining('服务暂时不可用'), findsOneWidget);
    expect(find.textContaining('保存为可信记忆'), findsNothing);
    expect(api.photoMemories, 0);
  });

  testWidgets('microphone denial fails visibly and creates no fake success', (tester) async {
    final api = _WidgetMediaApi();
    await pumpSection(tester, api, _WidgetMediaDevice(voicePermission: false));
    await tester.ensureVisible(find.byKey(const ValueKey('capture-voice-start')));
    await tester.tap(find.byKey(const ValueKey('capture-voice-start')));
    await tester.pumpAndSettle();
    expect(find.textContaining('麦克风权限未开启'), findsOneWidget);
    expect(find.textContaining('保存为可信记忆'), findsNothing);
  });
}


testWidgets('elder capture is voice-first and never records on page entry', (tester) async {
  final api = _WidgetMediaApi();
  final device = _WidgetMediaDevice(voicePermission: true);
  await pumpSection(tester, api, device, elderMode: true);
  await tester.pump();

  expect(find.text('帮我记一下'), findsOneWidget);
  expect(find.byKey(const ValueKey('elder-voice-start')), findsOneWidget);
  expect(find.byKey(const ValueKey('capture-voice-start')), findsNothing);
  expect(find.text('准备好了，点“开始说”'), findsOneWidget);
  expect(device.startCalls, 0);
  expect(api.mediaCreates, 0);
  expect(api.voiceMemories, 0);
})

testWidgets('elder voice requires explicit start stop and submit before canonical saved', (
  tester,
) async {
  final api = _WidgetMediaApi();
  final device = _WidgetMediaDevice(voicePermission: true);
  await pumpSection(tester, api, device, elderMode: true);

  await tester.tap(find.byKey(const ValueKey('elder-voice-start')));
  await tester.pump();
  expect(device.startCalls, 1);
  expect(device.recording, isTrue);
  expect(find.text('正在听你说'), findsOneWidget);
  expect(api.mediaCreates, 0);

  await tester.tap(find.byKey(const ValueKey('elder-voice-stop')));
  await tester.pumpAndSettle();
  expect(device.recording, isFalse);
  expect(find.text('已经录好了'), findsOneWidget);
  expect(api.mediaCreates, 0);
  expect(api.voiceMemories, 0);

  await tester.tap(find.byKey(const ValueKey('elder-voice-submit')));
  await tester.tap(find.byKey(const ValueKey('elder-voice-submit')));
  await tester.pumpAndSettle();

  expect(api.mediaCreates, 1);
  expect(api.signedPuts, 1);
  expect(api.mediaCompletes, 1);
  expect(api.voiceMemories, 1);
  expect(find.text('已经记住了'), findsOneWidget);
})

testWidgets('elder voice failure never renders saved state and keeps retry path', (
  tester,
) async {
  final api = _FailingCompleteMediaApi()
    ..accessToken = 'widget-token'
    ..authenticatedUserId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  final device = _WidgetMediaDevice(voicePermission: true);
  await pumpSection(tester, api, device, elderMode: true);

  await tester.tap(find.byKey(const ValueKey('elder-voice-start')));
  await tester.pump();
  await tester.tap(find.byKey(const ValueKey('elder-voice-stop')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const ValueKey('elder-voice-submit')));
  await tester.pumpAndSettle();

  expect(api.voiceMemories, 0);
  expect(find.text('已经记住了'), findsNothing);
  expect(find.text('这次没有保存成功'), findsOneWidget);
  expect(find.text('重试保存这段话'), findsOneWidget);
})


testWidgets('elder ASR failure stays FAILED and reuses the recorded clip for retry', (
  tester,
) async {
  final api = _FailingVoiceMemoryApi();
  final device = _WidgetMediaDevice(voicePermission: true);
  await pumpSection(tester, api, device, elderMode: true);

  await tester.tap(find.byKey(const ValueKey('elder-voice-start')));
  await tester.pump();
  await tester.tap(find.byKey(const ValueKey('elder-voice-stop')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const ValueKey('elder-voice-submit')));
  await tester.pumpAndSettle();

  expect(find.text('已经记住了'), findsNothing);
  expect(find.text('这次没有保存成功'), findsOneWidget);
  expect(find.text('重试保存这段话'), findsOneWidget);
  expect(find.textContaining('ASR_TIMEOUT'), findsOneWidget);
  expect(api.voiceMemories, 0);
})
