import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'capture_media.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

class UnifiedMediaCaptureSection extends StatefulWidget {
  const UnifiedMediaCaptureSection({
    super.key,
    required this.api,
    this.mediaDevice,
    this.mediaDeviceFactory,
    this.service,
  }) : assert(mediaDevice == null || mediaDeviceFactory == null);

  final JiYiApiClient api;
  final CaptureMediaDevice? mediaDevice;
  // [人工注释][S1-008] 仅用于验证“Widget 自己拥有 device 时 dispose 与 start-in-flight 的竞态”；
  // 生产默认仍创建 PlatformCaptureMediaDevice。
  final CaptureMediaDevice Function()? mediaDeviceFactory;
  final TrustedMediaCaptureService? service;

  @override
  State<UnifiedMediaCaptureSection> createState() =>
      _UnifiedMediaCaptureSectionState();
}

class _UnifiedMediaCaptureSectionState extends State<UnifiedMediaCaptureSection>
    with WidgetsBindingObserver {
  final photoTitleController = TextEditingController();
  final photoContentController = TextEditingController();
  final voiceTitleController = TextEditingController();

  CaptureMediaDevice? _deviceInstance;
  TrustedMediaCaptureService? _serviceInstance;
  PendingMediaFile? photo;
  PendingMediaFile? voice;
  Timer? _voiceLimitTimer;
  // [人工注释][S1-008] 生命周期 epoch 同时覆盖“正在启动”和“已经录音”，切后台会使当前 session 失效。
  int _voiceSessionEpoch = 0;
  bool _lifecycleAllowsRecording = true;
  bool _voiceLifecycleCancelInFlight = false;
  bool photoBusy = false;
  bool voiceBusy = false;
  bool voiceRecording = false;
  // 服务端记忆已成功、但本地临时图片删除失败时保留文件引用，
  // 只允许继续清理，不能再次提交同一业务操作。
  bool photoSavedPendingCleanup = false;
  // 服务端记忆已成功、但本地临时录音删除失败时保留文件引用，
  // 只允许继续清理，不能再次提交或开始下一段覆盖它。
  bool voiceSavedPendingCleanup = false;
  String? photoMessage;
  String? voiceMessage;
  JiYiStatusKind photoMessageKind = JiYiStatusKind.info;
  JiYiStatusKind voiceMessageKind = JiYiStatusKind.info;

  CaptureMediaDevice get _device =>
      _deviceInstance ??=
          widget.mediaDevice ??
          widget.mediaDeviceFactory?.call() ??
          PlatformCaptureMediaDevice();
  TrustedMediaCaptureService get _service =>
      _serviceInstance ??= widget.service ?? TrustedMediaCaptureService(widget.api);
  bool get _mediaBusy => photoBusy || voiceBusy || voiceRecording;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final lifecycleState = WidgetsBinding.instance.lifecycleState;
    _lifecycleAllowsRecording =
        lifecycleState == null || lifecycleState == AppLifecycleState.resumed;
    unawaited(_recoverLostPhoto());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final allowsRecording = state == AppLifecycleState.resumed;
    _lifecycleAllowsRecording = allowsRecording;
    if (allowsRecording) return;

    // [人工注释][S1-008] inactive/paused/hidden/detached 一律撤销当前录音 session；
    // Timer 只负责前台 60 秒上限，不能作为后台隐私边界。
    _voiceSessionEpoch += 1;
    _voiceLimitTimer?.cancel();
    _voiceLimitTimer = null;
    if (voiceRecording && !voiceBusy) {
      unawaited(_cancelVoiceForLifecycle());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _voiceSessionEpoch += 1;
    photoTitleController.dispose();
    photoContentController.dispose();
    voiceTitleController.dispose();
    _voiceLimitTimer?.cancel();
    _voiceLimitTimer = null;
    final device = _deviceInstance;
    final selectedPhoto = photo;
    final clip = voice;
    if (device != null) {
      if (selectedPhoto != null) {
        unawaited(_discardOwnedMediaSilently(device, selectedPhoto));
      }
      if (clip != null) {
        unawaited(_discardOwnedMediaSilently(device, clip));
      }
      // 内部 device.dispose() 自己负责取消活动录音；不能同时再发一次 cancel，
      // 否则原生 recorder 可能收到两个并发终止操作。
      if (widget.mediaDevice == null) {
        unawaited(_disposeMediaDeviceSilently(device));
      } else if (voiceRecording &&
          !voiceBusy &&
          !_voiceLifecycleCancelInFlight) {
        // [人工注释][S1-008] start/stop 或生命周期 cancel 已在飞行时不再并发发第二个 recorder 终止调用。
        unawaited(_cancelRecordingSilently(device));
      }
    }
    super.dispose();
  }

  Future<void> _recoverLostPhoto() async {
    try {
      final device = _device;
      final recovered = await device.recoverLostPhoto();
      if (recovered == null) return;
      if (!mounted) {
        await _discardOwnedMediaSilently(device, recovered);
        return;
      }
      if (photo != null) {
        await _discardOwnedMediaSilently(_device, recovered);
        return;
      }
      setState(() {
        photo = recovered;
        photoSavedPendingCleanup = false;
        photoMessageKind = JiYiStatusKind.info;
        photoMessage = '已恢复上次未完成的图片选择，提交前不会形成记忆。';
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          photoMessageKind = JiYiStatusKind.error;
          photoMessage = _errorMessage(error, '恢复上次图片失败');
        });
      }
    }
  }

  Future<void> _pickPhoto({required bool fromCamera}) async {
    if (_mediaBusy) return;
    setState(() {
      photoBusy = true;
      photoMessage = null;
    });
    try {
      final device = _device;
      final selected = await device.pickPhoto(fromCamera: fromCamera);
      if (selected == null) return;
      if (!mounted) {
        // [人工注释][S1-008] picker 返回时页面可能已经销毁；先释放 app-owned camera cache 再退出。
        await _discardOwnedMediaSilently(device, selected);
        return;
      }

      final previous = photo;
      if (previous != null) {
        try {
          await device.deleteOwnedFile(previous);
        } catch (_) {
          await _discardOwnedMediaSilently(device, selected);
          if (!mounted) return;
          setState(() {
            photoMessageKind = JiYiStatusKind.error;
            photoMessage = '旧的本地临时图片清理失败，请先清除后再选择新图片。';
          });
          return;
        }
      }
      if (!mounted) return;
      setState(() {
        photo = selected;
        photoSavedPendingCleanup = false;
        photoMessageKind = JiYiStatusKind.info;
        photoMessage = '已选择 ${selected.originalFilename ?? '图片'}，提交前不会形成记忆。';
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          photoMessageKind = JiYiStatusKind.error;
          photoMessage = _errorMessage(error, '选择图片失败');
        });
      }
    } finally {
      if (mounted) setState(() => photoBusy = false);
    }
  }

  Future<void> _submitPhoto() async {
    final selected = photo;
    if (selected == null || photoBusy) return;
    final content = photoContentController.text.trim();
    if (content.isEmpty) {
      setState(() {
        photoMessageKind = JiYiStatusKind.error;
        photoMessage = '请写下这张图片需要帮你记住的内容。';
      });
      return;
    }
    setState(() {
      photoBusy = true;
      photoMessageKind = JiYiStatusKind.info;
      photoMessage = '准备上传原始图片…';
    });
    try {
      await _service.submitPhoto(
        selected,
        title: photoTitleController.text,
        content: content,
        onPhase: (phase) {
          if (!mounted) return;
          setState(() {
            photoMessageKind = JiYiStatusKind.info;
            photoMessage = _photoPhaseText(phase);
          });
        },
      );
      var localCleanupFailed = false;
      try {
        await _device.deleteOwnedFile(selected);
      } catch (_) {
        // 服务端 Memory 已经权威成功；相机缓存删除失败只能降级为本地 warning。
        localCleanupFailed = true;
      }
      if (!mounted) return;
      photoTitleController.clear();
      photoContentController.clear();
      setState(() {
        if (localCleanupFailed) {
          photo = selected;
          photoSavedPendingCleanup = true;
          photoMessageKind = JiYiStatusKind.warning;
          photoMessage = '✓ 图片已验证并保存为可信记忆；本地临时图片清理失败，可再次清除。';
        } else {
          photo = null;
          photoSavedPendingCleanup = false;
          photoMessageKind = JiYiStatusKind.success;
          photoMessage = '✓ 图片已验证并保存为可信记忆';
        }
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          photoMessageKind = JiYiStatusKind.error;
          photoMessage = _errorMessage(error, '图片记录失败');
        });
      }
    } finally {
      if (mounted) setState(() => photoBusy = false);
    }
  }

  Future<void> _clearPhoto() async {
    final selected = photo;
    if (selected == null || photoBusy) return;
    final wasSaved = photoSavedPendingCleanup;
    try {
      await _device.deleteOwnedFile(selected);
    } catch (_) {
      if (mounted) {
        setState(() {
          photoMessageKind = JiYiStatusKind.error;
          photoMessage = '本地临时图片清理失败，请稍后重试。';
        });
      }
      return;
    }
    if (!mounted) return;
    photoTitleController.clear();
    photoContentController.clear();
    setState(() {
      photo = null;
      photoSavedPendingCleanup = false;
      photoMessageKind = JiYiStatusKind.info;
      photoMessage = wasSaved
          ? '本地临时图片已清除；已经保存的记忆不受影响。'
          : '图片已丢弃；未提交的图片不会成为记忆。';
    });
  }

  Future<void> _startVoiceRecording() async {
    if (_mediaBusy || voice != null) return;
    if (!_lifecycleAllowsRecording) {
      setState(() {
        voiceMessageKind = JiYiStatusKind.warning;
        voiceMessage = '请回到应用前台后再开始录音。';
      });
      return;
    }

    final sessionEpoch = ++_voiceSessionEpoch;
    final device = _device;
    setState(() {
      voiceBusy = true;
      voiceMessage = null;
    });
    try {
      final allowed = await device.startVoiceRecording();
      final invalidated = !mounted ||
          !_lifecycleAllowsRecording ||
          sessionEpoch != _voiceSessionEpoch;
      if (invalidated) {
        if (allowed && (mounted || widget.mediaDevice != null)) {
          // [人工注释][S1-008] start await 期间切后台时，原生 start 一返回就先 cancel，绝不进入可提交录音态。
          await _cancelRecordingSilently(device);
        }
        if (mounted) {
          setState(() {
            voiceRecording = false;
            voiceMessageKind = JiYiStatusKind.info;
            voiceMessage = '录音已因应用进入后台而取消；回到前台后可重新录制。';
          });
        }
        return;
      }
      if (!allowed) {
        setState(() {
          voiceMessageKind = JiYiStatusKind.error;
          voiceMessage = '麦克风权限未开启。请到系统设置中允许“迹忆”使用麦克风。';
        });
        return;
      }
      setState(() {
        voiceRecording = true;
        voiceMessageKind = JiYiStatusKind.info;
        voiceMessage = '正在录音…最长 60 秒。';
      });
      _voiceLimitTimer?.cancel();
      _voiceLimitTimer = Timer(
        const Duration(seconds: 60),
        () => unawaited(_stopVoiceRecording()),
      );
    } catch (error) {
      if (mounted) {
        setState(() {
          final terminationUnknown =
              error is RecorderTerminationUnknownException;
          // [人工注释][S1-008] start 抛错后若终止仍未知，必须保留“可能仍在录音”的 UI 状态。
          // 这样 Stop 入口仍在，Start 也不会重新开放。
          voiceRecording = terminationUnknown;
          if (terminationUnknown) {
            voice = null;
            voiceSavedPendingCleanup = false;
          }
          voiceMessageKind = JiYiStatusKind.error;
          voiceMessage = _errorMessage(error, '无法开始录音');
        });
      }
    } finally {
      if (mounted) setState(() => voiceBusy = false);
    }
  }

  Future<void> _cancelVoiceForLifecycle() async {
    if (_voiceLifecycleCancelInFlight || !voiceRecording) return;
    _voiceLifecycleCancelInFlight = true;
    setState(() => voiceBusy = true);
    try {
      await _device.cancelVoiceRecording();
      if (!mounted) return;
      setState(() {
        voiceRecording = false;
        voiceMessageKind = JiYiStatusKind.info;
        voiceMessage = '录音已因应用进入后台而取消；回到前台后可重新录制。';
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          // [人工注释][S1-008] cancel + hard-dispose 都失败时终止状态未知。
          // 保持 recording=true 锁住“开始录音”入口，并允许用户回前台后再次尝试停止。
          voiceRecording = true;
          voiceMessageKind = JiYiStatusKind.error;
          voiceMessage = _errorMessage(error, '后台切换时无法确认录音已停止');
        });
      }
    } finally {
      _voiceLifecycleCancelInFlight = false;
      if (mounted) setState(() => voiceBusy = false);
    }
  }

  Future<void> _stopVoiceRecording() async {
    if (!voiceRecording || voiceBusy) return;
    final sessionEpoch = _voiceSessionEpoch;
    final device = _device;
    _voiceLimitTimer?.cancel();
    _voiceLimitTimer = null;
    setState(() => voiceBusy = true);
    try {
      final clip = await device.stopVoiceRecording();
      final invalidated = !mounted ||
          !_lifecycleAllowsRecording ||
          sessionEpoch != _voiceSessionEpoch;
      if (invalidated) {
        if (clip != null) {
          await _discardOwnedMediaSilently(device, clip);
        }
        if (mounted) {
          setState(() {
            voiceRecording = false;
            voice = null;
            voiceSavedPendingCleanup = false;
            voiceMessageKind = JiYiStatusKind.info;
            voiceMessage = '录音已因应用进入后台而取消；不会上传或保存。';
          });
        }
        return;
      }
      setState(() {
        voiceRecording = false;
        voice = clip;
        voiceSavedPendingCleanup = false;
        voiceMessageKind =
            clip == null ? JiYiStatusKind.error : JiYiStatusKind.info;
        voiceMessage = clip == null
            ? '没有得到可提交的录音，请重新录制。'
            : '录音已暂存在本机，成功保存前不会成为记忆。';
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          final terminationUnknown =
              error is RecorderTerminationUnknownException;
          // [人工注释][S1-008] stop 失败但终止未知时不能切成 stopped。
          // 保留 Stop、锁住 Start；只有 device 已确认终止的普通 stop 错误才回到 false。
          voiceRecording = terminationUnknown;
          if (terminationUnknown) {
            voice = null;
            voiceSavedPendingCleanup = false;
          }
          voiceMessageKind = JiYiStatusKind.error;
          voiceMessage = _errorMessage(error, '停止录音失败');
        });
      }
    } finally {
      if (mounted) setState(() => voiceBusy = false);
    }
  }

  Future<void> _submitVoice() async {
    final clip = voice;
    if (clip == null ||
        voiceBusy ||
        voiceRecording ||
        voiceSavedPendingCleanup) {
      return;
    }
    setState(() {
      voiceBusy = true;
      voiceMessageKind = JiYiStatusKind.info;
      voiceMessage = '准备上传原始录音…';
    });
    try {
      await _service.submitVoice(
        clip,
        title: voiceTitleController.text,
        onPhase: (phase) {
          if (!mounted) return;
          setState(() {
            voiceMessageKind = JiYiStatusKind.info;
            voiceMessage = _voicePhaseText(phase);
          });
        },
      );
      var localCleanupFailed = false;
      try {
        await _device.deleteOwnedFile(clip);
      } catch (_) {
        // 服务端 Memory 已经权威成功；本地临时文件清理失败只能降级为 warning，
        // 绝不能把已成功的记忆误报为失败并诱导用户再次提交。
        localCleanupFailed = true;
      }
      if (!mounted) return;
      voiceTitleController.clear();
      setState(() {
        if (localCleanupFailed) {
          // 记忆已经成功，保留文件引用只为了让用户继续清理；
          // 不再展示提交入口，避免清理失败诱导重复业务提交。
          voice = clip;
          voiceSavedPendingCleanup = true;
          voiceMessageKind = JiYiStatusKind.warning;
          voiceMessage = '✓ 录音已验证并保存为可信记忆；本地临时录音清理失败，可再次清除。';
        } else {
          voice = null;
          voiceSavedPendingCleanup = false;
          voiceMessageKind = JiYiStatusKind.success;
          voiceMessage = '✓ 录音已验证并保存为可信记忆';
        }
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          voiceMessageKind = JiYiStatusKind.error;
          voiceMessage = '${_errorMessage(error, '语音记录失败')} 本地录音已保留，可直接重试。';
        });
      }
    } finally {
      if (mounted) setState(() => voiceBusy = false);
    }
  }

  Future<void> _clearVoice() async {
    final clip = voice;
    if (clip == null || voiceBusy || voiceRecording) return;
    final wasSaved = voiceSavedPendingCleanup;
    try {
      await _device.deleteOwnedFile(clip);
    } catch (_) {
      if (mounted) {
        setState(() {
          voiceMessageKind = JiYiStatusKind.error;
          voiceMessage = '本地临时录音清理失败，请稍后重试。';
        });
      }
      return;
    }
    if (!mounted) return;
    voiceTitleController.clear();
    setState(() {
      voice = null;
      voiceSavedPendingCleanup = false;
      voiceMessageKind = JiYiStatusKind.info;
      voiceMessage = wasSaved
          ? '本地临时录音已清除；已经保存的记忆不受影响。'
          : '本地临时录音已清除；未提交的录音不会成为记忆。';
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        JiYiSectionCard(
          leading: Icon(Icons.photo_camera_outlined, color: theme.colorScheme.primary),
          title: '图片记一下',
          subtitle: '只处理你主动选择或用相机记录的图片；不会在后台处理相册。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      key: const ValueKey('capture-photo-camera'),
                      onPressed: _mediaBusy ? null : () => _pickPhoto(fromCamera: true),
                      icon: const Icon(Icons.photo_camera_outlined),
                      label: const Text('相机'),
                    ),
                  ),
                  const SizedBox(width: JiYiSpacing.sm),
                  Expanded(
                    child: OutlinedButton.icon(
                      key: const ValueKey('capture-photo-gallery'),
                      onPressed: _mediaBusy ? null : () => _pickPhoto(fromCamera: false),
                      icon: const Icon(Icons.photo_library_outlined),
                      label: const Text('从相册选择'),
                    ),
                  ),
                ],
              ),
              if (photo != null && !photoSavedPendingCleanup) ...[
                const SizedBox(height: JiYiSpacing.sm),
                TextField(
                  key: const ValueKey('capture-photo-title'),
                  controller: photoTitleController,
                  decoration: const InputDecoration(labelText: '图片标题（可选）'),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                TextField(
                  key: const ValueKey('capture-photo-content'),
                  controller: photoContentController,
                  minLines: 2,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    labelText: '这张图片需要记住什么',
                    hintText: '例如：这是出差报销需要的酒店发票。',
                    alignLabelWithHint: true,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                FilledButton.icon(
                  key: const ValueKey('capture-photo-submit'),
                  onPressed: photoBusy ? null : _submitPhoto,
                  icon: const Icon(Icons.cloud_upload_outlined),
                  label: Text(photoBusy ? '正在处理…' : '上传并帮我记住'),
                ),
                const SizedBox(height: JiYiSpacing.xs),
                OutlinedButton.icon(
                  key: const ValueKey('capture-photo-clear'),
                  onPressed: photoBusy ? null : _clearPhoto,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('丢弃这张图片'),
                ),
              ] else if (photo != null) ...[
                const SizedBox(height: JiYiSpacing.sm),
                OutlinedButton.icon(
                  key: const ValueKey('capture-photo-clear'),
                  onPressed: photoBusy ? null : _clearPhoto,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('再次清除本地临时图片'),
                ),
              ],
              if (photoMessage != null) ...[
                const SizedBox(height: JiYiSpacing.sm),
                JiYiStatusBanner(kind: photoMessageKind, message: photoMessage!),
              ],
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          leading: Icon(Icons.mic_none_outlined, color: theme.colorScheme.primary),
          title: '录一句',
          subtitle: '只在你主动操作时录音，最长 60 秒；录音完成并验证后才会保存。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (voiceRecording)
                FilledButton.icon(
                  key: const ValueKey('capture-voice-stop'),
                  onPressed: voiceBusy ? null : _stopVoiceRecording,
                  icon: const Icon(Icons.stop_circle_outlined),
                  label: const Text('停止录音'),
                )
              else if (voice == null)
                FilledButton.tonalIcon(
                  key: const ValueKey('capture-voice-start'),
                  onPressed: _mediaBusy ? null : _startVoiceRecording,
                  icon: const Icon(Icons.mic_none_outlined),
                  label: const Text('开始录音'),
                ),
              if (voice != null && !voiceSavedPendingCleanup) ...[
                const SizedBox(height: JiYiSpacing.sm),
                TextField(
                  key: const ValueKey('capture-voice-title'),
                  controller: voiceTitleController,
                  decoration: const InputDecoration(labelText: '语音标题（可选）'),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                FilledButton.icon(
                  key: const ValueKey('capture-voice-submit'),
                  onPressed: voiceBusy ? null : _submitVoice,
                  icon: const Icon(Icons.graphic_eq),
                  label: Text(voiceBusy ? '正在处理…' : '上传、转写并帮我记住'),
                ),
                const SizedBox(height: JiYiSpacing.xs),
                OutlinedButton.icon(
                  key: const ValueKey('capture-voice-clear'),
                  onPressed: voiceBusy ? null : _clearVoice,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('清除本地临时录音'),
                ),
              ] else if (voice != null) ...[
                const SizedBox(height: JiYiSpacing.sm),
                OutlinedButton.icon(
                  key: const ValueKey('capture-voice-clear'),
                  onPressed: voiceBusy ? null : _clearVoice,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('再次清除本地临时录音'),
                ),
              ],
              if (voiceMessage != null) ...[
                const SizedBox(height: JiYiSpacing.sm),
                JiYiStatusBanner(kind: voiceMessageKind, message: voiceMessage!),
              ],
            ],
          ),
        ),
      ],
    );
  }
}


Future<void> _disposeMediaDeviceSilently(CaptureMediaDevice device) async {
  try {
    await device.dispose();
  } catch (_) {
    // 页面已退出时不再向用户弹错误，但不能把异步 dispose 异常泄漏到全局 Zone。
  }
}

Future<void> _cancelRecordingSilently(CaptureMediaDevice device) async {
  try {
    await device.cancelVoiceRecording();
  } catch (_) {
    // 页面已退出时只能 best-effort 终止录音。
  }
}

Future<void> _discardOwnedMediaSilently(
  CaptureMediaDevice device,
  PendingMediaFile file,
) async {
  try {
    await device.deleteOwnedFile(file);
  } catch (_) {
    // Widget 已销毁时无法再向用户反馈；这里只做 best-effort 临时文件清理。
  }
}

String _errorMessage(Object error, String fallback) {
  if (error is ApiException) {
    if (error.statusCode == 409 &&
        error.message == 'MEDIA_MEMORY_IDEMPOTENCY_CONFLICT') {
      return '服务器已经保存了这个媒体的另一版内容；为避免误报成功，请查看已保存的记忆后再决定是否新建。';
    }
    return error.message;
  }
  if (error is TransportException) return error.message;
  if (error is ProtocolException) return error.message;
  if (error is CaptureMediaException) return error.message;
  return fallback;
}

String _photoPhaseText(MediaSubmissionPhase phase) {
  return switch (phase) {
    MediaSubmissionPhase.uploading => '正在上传原始图片…',
    MediaSubmissionPhase.verifying => '正在验证图片…',
    MediaSubmissionPhase.saving => '正在保存图片记忆…',
    MediaSubmissionPhase.transcribing => '正在处理…',
  };
}

String _voicePhaseText(MediaSubmissionPhase phase) {
  return switch (phase) {
    MediaSubmissionPhase.uploading => '正在上传原始录音…',
    MediaSubmissionPhase.verifying => '正在验证录音…',
    MediaSubmissionPhase.transcribing => '正在把录音转成文字并检查结果…',
    MediaSubmissionPhase.saving => '正在保存语音记忆…',
  };
}
