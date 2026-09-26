import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:image_picker/image_picker.dart';
import 'package:record/record.dart';

import 'api_client.dart';

class CaptureMediaException implements Exception {
  CaptureMediaException(this.message);
  final String message;
  @override
  String toString() => message;
}

// [人工注释][S1-008] 录音“是否已经终止”未知属于隐私状态，不是普通采集失败。
// UI 必须据此保留 Stop/锁住 Start，不能把它降级成普通错误文案。
class RecorderTerminationUnknownException extends CaptureMediaException {
  RecorderTerminationUnknownException(super.message);
}

class PendingMediaFile {
  PendingMediaFile({
    required this.clientUploadId,
    required this.contentType,
    required this.sizeBytes,
    required this.originalFilename,
    required this.occurredAt,
    required Future<List<int>> Function() readBytes,
    this.localPath,
    this.ownsLocalFile = false,
  }) : _readBytes = readBytes;

  factory PendingMediaFile.fromPath({
    required String path,
    required String clientUploadId,
    required String contentType,
    required int sizeBytes,
    required String? originalFilename,
    required DateTime occurredAt,
    bool ownsLocalFile = false,
  }) {
    return PendingMediaFile(
      clientUploadId: clientUploadId,
      contentType: contentType,
      sizeBytes: sizeBytes,
      originalFilename: originalFilename,
      occurredAt: occurredAt,
      localPath: path,
      ownsLocalFile: ownsLocalFile,
      readBytes: () => File(path).readAsBytes(),
    );
  }

  final String clientUploadId;
  final String contentType;
  final int sizeBytes;
  final String? originalFilename;
  final DateTime occurredAt;
  final String? localPath;
  final bool ownsLocalFile;
  final Future<List<int>> Function() _readBytes;

  Future<List<int>> readBytes() => _readBytes();
}

abstract class CaptureMediaDevice {
  Future<PendingMediaFile?> pickPhoto({required bool fromCamera});
  Future<PendingMediaFile?> recoverLostPhoto();
  Future<bool> startVoiceRecording();
  Future<PendingMediaFile?> stopVoiceRecording();
  Future<void> cancelVoiceRecording();
  Future<void> deleteOwnedFile(PendingMediaFile file);
  Future<void> dispose();
}

String newCaptureClientUuid() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
      '${hex.substring(20)}';
}

Set<String> _isoBmffBrands(List<int> prefix) {
  if (prefix.length < 16 ||
      String.fromCharCodes(prefix.sublist(4, 8)) != 'ftyp') {
    return const {};
  }
  final boxSize = (prefix[0] << 24) |
      (prefix[1] << 16) |
      (prefix[2] << 8) |
      prefix[3];
  if (boxSize < 16) return const {};
  final end = min(prefix.length, boxSize);
  final brands = <String>{String.fromCharCodes(prefix.sublist(8, 12))};
  for (var offset = 16; offset + 4 <= end; offset += 4) {
    brands.add(String.fromCharCodes(prefix.sublist(offset, offset + 4)));
  }
  return brands;
}

String? detectImageContentTypeFromPrefix(List<int> prefix) {
  if (prefix.length >= 3 &&
      prefix[0] == 0xff &&
      prefix[1] == 0xd8 &&
      prefix[2] == 0xff) {
    return 'image/jpeg';
  }
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (prefix.length >= png.length) {
    var pngMatches = true;
    for (var index = 0; index < png.length; index++) {
      if (prefix[index] != png[index]) {
        pngMatches = false;
        break;
      }
    }
    if (pngMatches) return 'image/png';
  }
  if (prefix.length >= 12 &&
      String.fromCharCodes(prefix.sublist(0, 4)) == 'RIFF' &&
      String.fromCharCodes(prefix.sublist(8, 12)) == 'WEBP') {
    return 'image/webp';
  }
  final brands = _isoBmffBrands(prefix);
  const heicBrands = {
    'heic', 'heix', 'hevc', 'hevx', 'heim', 'heis', 'hevm', 'hevs',
  };
  if (brands.any(heicBrands.contains)) return 'image/heic';
  const heifBrands = {'mif1', 'msf1'};
  if (brands.any(heifBrands.contains)) return 'image/heif';
  return null;
}

Future<List<int>> _readPrefix(File file, int maxBytes) async {
  final handle = await file.open();
  try {
    return await handle.read(maxBytes);
  } finally {
    await handle.close();
  }
}

abstract class CaptureAudioRecorder {
  Future<bool> isRecording();
  Future<bool> hasPermission();
  Future<void> start(RecordConfig config, {required String path});
  Future<String?> stop();
  Future<void> cancel();
  Future<void> dispose();
}

// [人工注释][S1-008] 原生 record 插件隔离在这个适配器后，便于对“异常录音文件必须清理”做无平台依赖回归。
class _PluginCaptureAudioRecorder implements CaptureAudioRecorder {
  _PluginCaptureAudioRecorder() : _inner = AudioRecorder();

  final AudioRecorder _inner;

  @override
  Future<bool> isRecording() => _inner.isRecording();

  @override
  Future<bool> hasPermission() => _inner.hasPermission();

  @override
  Future<void> start(RecordConfig config, {required String path}) =>
      _inner.start(config, path: path);

  @override
  Future<String?> stop() => _inner.stop();

  @override
  Future<void> cancel() => _inner.cancel();

  @override
  Future<void> dispose() => _inner.dispose();
}

Future<void> _deleteLocalPathBestEffort(String path) async {
  try {
    final file = File(path);
    if (await file.exists()) await file.delete();
  } catch (_) {
    // [人工注释][S1-008] 临时文件清理不能覆盖原始采集错误；调用方仍会收到原始失败。
  }
}

class PlatformCaptureMediaDevice implements CaptureMediaDevice {
  PlatformCaptureMediaDevice({
    ImagePicker? imagePicker,
    CaptureAudioRecorder? recorder,
  })  : _imagePicker = imagePicker ?? ImagePicker(),
        _recorder = recorder,
        _canRecreateRecorder = recorder == null;

  final ImagePicker _imagePicker;
  final bool _canRecreateRecorder;
  CaptureAudioRecorder? _recorder;

  // [人工注释][S1-008] Device 层自行串行化 recorder 操作，不再把 start/cancel/dispose 的正确性
  // 建立在具体插件内部 semaphore 的实现细节上。
  Future<void> _recorderQueue = Future<void>.value();
  bool _disposeRequested = false;
  bool _disposed = false;
  bool _terminationUnknown = false;

  String? _activeVoicePath;
  String? _activeVoiceClientUploadId;
  DateTime? _activeVoiceOccurredAt;

  Future<T> _runRecorderOperation<T>(Future<T> Function() operation) {
    final previous = _recorderQueue;
    final done = Completer<void>();
    _recorderQueue = done.future;
    return () async {
      await previous;
      try {
        return await operation();
      } finally {
        if (!done.isCompleted) done.complete();
      }
    }();
  }

  CaptureAudioRecorder _recorderForStartLocked() {
    if (_disposeRequested || _disposed) {
      throw CaptureMediaException('录音设备正在关闭，请重新进入页面后再试');
    }
    if (_terminationUnknown) {
      throw RecorderTerminationUnknownException(
        '上一次录音是否停止无法确认，请关闭当前页面后重试',
      );
    }
    final existing = _recorder;
    if (existing != null) return existing;
    if (!_canRecreateRecorder) {
      throw CaptureMediaException('录音设备已关闭，请重新进入页面后再试');
    }
    final created = _PluginCaptureAudioRecorder();
    _recorder = created;
    return created;
  }

  void _clearActiveVoiceSession() {
    _activeVoicePath = null;
    _activeVoiceClientUploadId = null;
    _activeVoiceOccurredAt = null;
  }

  void _markRecorderDisposed(CaptureAudioRecorder recorder) {
    if (identical(_recorder, recorder)) {
      _recorder = null;
    }
  }

  Future<void> _hardDisposeRecorderLocked(CaptureAudioRecorder recorder) async {
    try {
      await recorder.dispose();
      _markRecorderDisposed(recorder);
    } catch (_) {
      _terminationUnknown = true;
      throw RecorderTerminationUnknownException(
        '无法确认录音已经停止。为保护隐私，当前录音入口已锁定，请关闭应用后重试。',
      );
    }
  }

  Future<void> _terminateRecorderLocked(CaptureAudioRecorder recorder) async {
    try {
      await recorder.cancel();
    } catch (_) {
      // [人工注释][S1-008] cancel 失败时不能假装已停止；立刻用 dispose 做硬终止。
      // 只有 hard dispose 成功才允许清除 session 身份。
      await _hardDisposeRecorderLocked(recorder);
    }
  }

  Future<void> _terminateActiveVoiceLocked(
    CaptureAudioRecorder recorder, {
    String? explicitPath,
  }) async {
    final path = explicitPath ?? _activeVoicePath;
    await _terminateRecorderLocked(recorder);
    _terminationUnknown = false;
    _clearActiveVoiceSession();
    if (path != null) {
      await _deleteLocalPathBestEffort(path);
    }
  }

  Future<PendingMediaFile> _pendingPhotoFromXFile(
    XFile picked, {
    required bool ownsLocalFile,
  }) async {
    try {
      final file = File(picked.path);
      final size = await file.length();
      if (size <= 0) throw CaptureMediaException('图片文件为空');
      final contentType =
          detectImageContentTypeFromPrefix(await _readPrefix(file, 64));
      if (contentType == null) {
        throw CaptureMediaException('仅支持 JPEG、PNG、WebP、HEIC、HEIF 图片');
      }
      return PendingMediaFile.fromPath(
        path: picked.path,
        clientUploadId: newCaptureClientUuid(),
        contentType: contentType,
        sizeBytes: size,
        originalFilename: picked.name.trim().isEmpty ? null : picked.name,
        occurredAt: DateTime.now().toUtc(),
        ownsLocalFile: ownsLocalFile,
      );
    } catch (_) {
      // [人工注释][S1-008] 相机结果属于应用 cache；在 PendingMediaFile 建立前失败也必须 best-effort 删除。
      if (ownsLocalFile) await _deleteLocalPathBestEffort(picked.path);
      rethrow;
    }
  }

  @override
  Future<PendingMediaFile?> pickPhoto({required bool fromCamera}) async {
    final picked = await _imagePicker.pickImage(
      source: fromCamera ? ImageSource.camera : ImageSource.gallery,
      imageQuality: 100,
    );
    if (picked == null) return null;

    // Camera 结果位于应用本地 cache，由迹忆负责明确清理。
    // Gallery 结果不声明删除所有权，避免误删用户照片库资产。
    return _pendingPhotoFromXFile(picked, ownsLocalFile: fromCamera);
  }

  @override
  Future<PendingMediaFile?> recoverLostPhoto() async {
    if (!Platform.isAndroid) return null;
    final response = await _imagePicker.retrieveLostData();
    if (response.isEmpty) return null;
    if (response.exception != null) {
      throw CaptureMediaException('恢复上次图片失败，请重新选择');
    }
    final files = response.files;
    if (files == null || files.isEmpty) return null;

    // Activity 被系统回收后 image_picker 不保留原 source 类型。
    // 恢复文件只重新挂回 UI，不声明删除所有权，优先避免误删图库资产。
    return _pendingPhotoFromXFile(files.first, ownsLocalFile: false);
  }

  @override
  Future<bool> startVoiceRecording() {
    return _runRecorderOperation(() async {
      final recorder = _recorderForStartLocked();
      if (await recorder.isRecording()) {
        throw CaptureMediaException('已有录音正在进行');
      }
      if (_disposeRequested) {
        throw CaptureMediaException('录音设备正在关闭，请重新进入页面后再试');
      }
      if (!await recorder.hasPermission()) return false;
      if (_disposeRequested) {
        throw CaptureMediaException('录音设备正在关闭，请重新进入页面后再试');
      }

      final clientUploadId = newCaptureClientUuid();
      final path = '${Directory.systemTemp.path}${Platform.pathSeparator}'
          'jiyidashi-voice-$clientUploadId.m4a';

      // [人工注释][S1-008] 在 native start await 之前先登记 session。
      // 这样 dispose/cancel 永远能看见正在启动的录音，不存在“late success 后才获得身份”的窗口。
      _activeVoicePath = path;
      _activeVoiceClientUploadId = clientUploadId;
      _activeVoiceOccurredAt = DateTime.now().toUtc();

      try {
        await recorder.start(
          const RecordConfig(
            encoder: AudioEncoder.aacLc,
            bitRate: 128000,
            sampleRate: 44100,
            numChannels: 1,
          ),
          path: path,
        );
      } catch (_) {
        // [人工注释][S1-008] native start 抛错不能等同于“绝对没开始”。
        // 必须复用同一终止确认链：cancel -> hard dispose；确认终止后才清 session。
        try {
          await _terminateActiveVoiceLocked(recorder, explicitPath: path);
        } on RecorderTerminationUnknownException {
          rethrow;
        }
        rethrow;
      }

      if (_disposeRequested) {
        // dispose() 在 start await 中到达：start 晚到成功也必须在本操作返回前完成终止。
        await _terminateActiveVoiceLocked(recorder, explicitPath: path);
        throw CaptureMediaException('录音设备已关闭');
      }
      return true;
    });
  }

  @override
  Future<PendingMediaFile?> stopVoiceRecording() {
    return _runRecorderOperation(() async {
      final expectedPath = _activeVoicePath;
      final clientUploadId = _activeVoiceClientUploadId;
      final occurredAt = _activeVoiceOccurredAt;
      if (expectedPath == null || clientUploadId == null || occurredAt == null) {
        return null;
      }
      final recorder = _recorder;
      if (recorder == null) {
        _terminationUnknown = true;
        throw RecorderTerminationUnknownException(
          '无法确认录音已经停止。为保护隐私，当前录音入口已锁定，请关闭应用后重试。',
        );
      }

      String? stoppedPath;
      try {
        stoppedPath = await recorder.stop();
      } catch (_) {
        try {
          await _terminateActiveVoiceLocked(
            recorder,
            explicitPath: expectedPath,
          );
        } catch (_) {
          rethrow;
        }
        rethrow;
      }

      final path = stoppedPath ?? expectedPath;
      _terminationUnknown = false;
      _clearActiveVoiceSession();
      try {
        final file = File(path);
        if (!await file.exists()) {
          throw CaptureMediaException('录音文件不存在，请重新录制');
        }
        final size = await file.length();
        if (size <= 0) {
          throw CaptureMediaException('录音文件为空，请重新录制');
        }

        if (path != expectedPath) {
          try {
            final staleExpected = File(expectedPath);
            if (await staleExpected.exists()) await staleExpected.delete();
          } catch (_) {
            // [人工注释][S1-008] recorder 改写输出路径时不能静默遗留另一份 app-owned 临时录音。
            throw CaptureMediaException('录音临时文件清理失败，请重新录制');
          }
        }
        return PendingMediaFile.fromPath(
          path: path,
          clientUploadId: clientUploadId,
          contentType: 'audio/mp4',
          sizeBytes: size,
          originalFilename: 'voice.m4a',
          occurredAt: occurredAt,
          ownsLocalFile: true,
        );
      } catch (_) {
        // [人工注释][S1-008] stop 已结束原生 session 后，任何本地校验失败都清理本次可能产生的全部路径。
        await _deleteLocalPathBestEffort(path);
        if (path != expectedPath) {
          await _deleteLocalPathBestEffort(expectedPath);
        }
        rethrow;
      }
    });
  }

  @override
  Future<void> cancelVoiceRecording() {
    return _runRecorderOperation(() async {
      final recorder = _recorder;
      if (recorder == null) {
        if (_activeVoicePath == null) {
          _terminationUnknown = false;
          return;
        }
        _terminationUnknown = true;
        throw RecorderTerminationUnknownException(
          '无法确认录音已经停止。为保护隐私，当前录音入口已锁定，请关闭应用后重试。',
        );
      }
      await _terminateActiveVoiceLocked(recorder);
    });
  }

  @override
  Future<void> deleteOwnedFile(PendingMediaFile file) async {
    if (!file.ownsLocalFile || file.localPath == null) return;
    final local = File(file.localPath!);
    if (await local.exists()) await local.delete();
  }

  @override
  Future<void> dispose() {
    // [人工注释][S1-008] 必须在任何 await 之前同步置位；正在执行的 start 会在 native 返回后看见它并自行终止。
    _disposeRequested = true;
    return _runRecorderOperation(() async {
      if (_disposed) return;

      var recorder = _recorder;
      if (recorder == null) {
        if (_activeVoicePath != null) {
          _terminationUnknown = true;
          throw RecorderTerminationUnknownException(
            '无法确认录音已经停止。为保护隐私，请完全关闭应用。',
          );
        }
        _disposed = true;
        return;
      }

      if (_activeVoicePath != null || _terminationUnknown) {
        try {
          await _terminateActiveVoiceLocked(recorder);
        } catch (_) {
          // cancel + hard-dispose 都失败时再做一次最终 hard-dispose 重试；
          // 若仍失败，保留 session/unknown 状态，绝不伪装成已停止。
          await _hardDisposeRecorderLocked(recorder);
          _terminationUnknown = false;
          final path = _activeVoicePath;
          _clearActiveVoiceSession();
          if (path != null) await _deleteLocalPathBestEffort(path);
        }
      } else {
        bool mayBeRecording;
        try {
          mayBeRecording = await recorder.isRecording();
        } catch (_) {
          mayBeRecording = true;
        }
        if (mayBeRecording) {
          await _terminateActiveVoiceLocked(recorder);
        }
      }

      recorder = _recorder;
      if (recorder != null) {
        await recorder.dispose();
        _markRecorderDisposed(recorder);
      }
      _disposed = true;
    });
  }
}

enum MediaSubmissionPhase { uploading, verifying, saving, transcribing }

class TrustedMediaCaptureService {
  TrustedMediaCaptureService(this.api);
  final JiYiApiClient api;

  ({int version, String owner}) _captureSession() {
    final owner = api.authenticatedUserId?.trim();
    if (owner == null || owner.isEmpty) {
      throw ApiException(401, '请先登录');
    }
    return (version: api.sessionVersion, owner: owner);
  }

  void _assertSameSession(({int version, String owner}) session) {
    if (api.sessionVersion != session.version ||
        api.authenticatedUserId != session.owner) {
      throw ProtocolException('登录状态已变化；本次记录已停止，请在当前账号重新操作');
    }
  }

  Future<String> submitPhoto(
    PendingMediaFile file, {
    String? title,
    required String content,
    void Function(MediaSubmissionPhase phase)? onPhase,
  }) async {
    final session = _captureSession();
    onPhase?.call(MediaSubmissionPhase.uploading);
    _assertSameSession(session);
    final upload = await api.createMediaUpload(
      clientUploadId: file.clientUploadId,
      kind: 'IMAGE',
      contentType: file.contentType,
      sizeBytes: file.sizeBytes,
      originalFilename: file.originalFilename,
    );
    _assertSameSession(session);
    await _uploadIfNeeded(upload, file, session);
    _assertSameSession(session);
    onPhase?.call(MediaSubmissionPhase.verifying);
    _assertSameSession(session);
    await api.completeMediaUpload(upload.mediaId);
    _assertSameSession(session);
    onPhase?.call(MediaSubmissionPhase.saving);
    _assertSameSession(session);
    final response = await api.createPhotoMemory(
      mediaId: upload.mediaId,
      title: title,
      content: content,
      occurredAt: file.occurredAt,
    );
    _assertSameSession(session);
    return _memoryId(response);
  }

  Future<String> submitVoice(
    PendingMediaFile file, {
    String? title,
    void Function(MediaSubmissionPhase phase)? onPhase,
  }) async {
    final session = _captureSession();
    onPhase?.call(MediaSubmissionPhase.uploading);
    _assertSameSession(session);
    final upload = await api.createMediaUpload(
      clientUploadId: file.clientUploadId,
      kind: 'AUDIO',
      contentType: file.contentType,
      sizeBytes: file.sizeBytes,
      originalFilename: file.originalFilename,
    );
    _assertSameSession(session);
    await _uploadIfNeeded(upload, file, session);
    _assertSameSession(session);
    onPhase?.call(MediaSubmissionPhase.verifying);
    _assertSameSession(session);
    await api.completeMediaUpload(upload.mediaId);
    _assertSameSession(session);
    onPhase?.call(MediaSubmissionPhase.transcribing);
    _assertSameSession(session);
    final response = await api.createVoiceMemory(
      mediaId: upload.mediaId,
      title: title,
      occurredAt: file.occurredAt,
    );
    _assertSameSession(session);
    return _memoryId(response);
  }

  Future<void> _uploadIfNeeded(
    MediaUploadSession upload,
    PendingMediaFile file,
    ({int version, String owner}) session,
  ) async {
    final target = upload.upload;
    if (target == null) return;
    final bytes = await file.readBytes();
    _assertSameSession(session);
    if (bytes.length != file.sizeBytes) {
      throw CaptureMediaException('媒体文件在提交前发生变化，请重新选择或录制');
    }
    _assertSameSession(session);
    await api.uploadSignedMedia(target, bytes);
    _assertSameSession(session);
  }

  String _memoryId(Map<String, dynamic> response) {
    final memory = response['memory'];
    final id = memory is Map<String, dynamic> ? memory['id'] : null;
    if (id is! String || id.trim().isEmpty) {
      throw ProtocolException('服务端返回格式不正确');
    }
    return id;
  }
}
