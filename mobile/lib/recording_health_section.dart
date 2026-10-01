import 'package:flutter/material.dart';

import 'api_client.dart';
import 'native_location_controller.dart';
import 'offline_queue.dart';
import 'recording_health.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

class RecordingHealthSection extends StatefulWidget {
  const RecordingHealthSection({
    super.key,
    required this.api,
    required this.store,
    this.nativeLocationController,
  });

  final JiYiApiClient api;
  final OfflineQueueStore store;
  final NativeLocationController? nativeLocationController;

  @override
  State<RecordingHealthSection> createState() => _RecordingHealthSectionState();
}

class _RecordingHealthSectionState extends State<RecordingHealthSection> {
  RecordingHealthView? _view;
  bool _loading = true;
  String? _error;
  int _requestEpoch = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  bool _isCurrent(int epoch, int sessionVersion, String owner) {
    return mounted &&
        epoch == _requestEpoch &&
        widget.api.sessionVersion == sessionVersion &&
        widget.api.authenticatedUserId == owner;
  }

  Future<void> _refresh() async {
    final owner = widget.api.authenticatedUserId?.trim();
    if (owner == null || owner.isEmpty) {
      if (mounted) {
        setState(() {
          _view = const RecordingHealthView.unknown(reason: 'NO_SESSION');
          _loading = false;
          _error = '当前登录状态无法确认记录健康状态。';
        });
      }
      return;
    }

    final epoch = ++_requestEpoch;
    final sessionVersion = widget.api.sessionVersion;
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }

    try {
      Map<String, dynamic>? clientState;
      final controller = widget.nativeLocationController;
      if (controller != null) {
        // Read-only refresh: it cannot request permission or start the producer.
        await controller.refresh();
        if (!_isCurrent(epoch, sessionVersion, owner)) return;
        final native = controller.status;
        if (native != null && native.supported) {
          try {
            final sqlite = await widget.store.locationQueueDiagnostics(owner);
            if (!_isCurrent(epoch, sessionVersion, owner)) return;
            clientState = buildRecordingHealthClientState(
              status: native,
              sqliteQueue: sqlite,
            );
          } catch (_) {
            // Missing local evidence must become UNKNOWN, never a fabricated healthy state.
            clientState = null;
          }
        }
      }

      final raw = await widget.api.getRecordingHealth(clientState: clientState);
      if (!_isCurrent(epoch, sessionVersion, owner)) return;
      final parsed = RecordingHealthView.fromJson(raw);
      setState(() {
        _view = parsed;
        _loading = false;
        _error = parsed.malformed ? '记录状态返回不完整，已按未知状态处理。' : null;
      });
    } on TransportException {
      if (!_isCurrent(epoch, sessionVersion, owner)) return;
      setState(() {
        _view = const RecordingHealthView.unknown(reason: 'NETWORK_UNAVAILABLE');
        _loading = false;
        _error = '暂时无法向服务器确认记录状态。';
      });
    } on ApiException catch (error) {
      if (!_isCurrent(epoch, sessionVersion, owner)) return;
      setState(() {
        _view = const RecordingHealthView.unknown(reason: 'SERVER_REJECTED');
        _loading = false;
        _error = error.statusCode == 401
            ? '登录状态已变化，无法确认记录状态。'
            : '服务器暂时无法确认记录状态。';
      });
    } on ProtocolException {
      if (!_isCurrent(epoch, sessionVersion, owner)) return;
      setState(() {
        _view = const RecordingHealthView.unknown();
        _loading = false;
        _error = '记录状态返回不完整，已按未知状态处理。';
      });
    } catch (_) {
      if (!_isCurrent(epoch, sessionVersion, owner)) return;
      setState(() {
        _view = const RecordingHealthView.unknown();
        _loading = false;
        _error = '暂时无法确认记录状态。';
      });
    }
  }

  Future<void> _runHealthAction(RecordingHealthAction action) async {
    if (_loading) return;
    final controller = widget.nativeLocationController;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      switch (action) {
        case RecordingHealthAction.resumePrivacy:
          await widget.api.resumeMemory();
          if (controller != null) {
            await controller.resumeAfterPrivacy();
          }
          break;
        case RecordingHealthAction.requestForegroundPermission:
          if (controller == null) return;
          await controller.requestForegroundPermission();
          break;
        case RecordingHealthAction.enableAutomaticLocation:
          if (controller == null) return;
          await controller.enableAutomaticLocation();
          break;
        case RecordingHealthAction.startProducer:
          if (controller == null) return;
          await controller.start();
          break;
        case RecordingHealthAction.openLocationServicesSettings:
          if (controller == null) return;
          await controller.openLocationServicesSettings();
          break;
        case RecordingHealthAction.openBackgroundLocationSettings:
          if (controller == null) return;
          await controller.openBackgroundLocationSettings();
          break;
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = '操作未完成，请按系统提示处理后重新确认。';
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
        await _refresh();
      }
    }
  }

  bool _canRenderAction(RecordingHealthAction action) {
    if (action == RecordingHealthAction.resumePrivacy) return true;
    return widget.nativeLocationController != null;
  }

  @override
  Widget build(BuildContext context) {
    final view = _view;
    final suggested = view?.suggestedAction;
    final nativeReason = widget.nativeLocationController?.status?.reason;
    final action = suggested == RecordingHealthAction.enableAutomaticLocation &&
            nativeReason == 'background_settings_required'
        ? RecordingHealthAction.openBackgroundLocationSettings
        : suggested;
    return JiYiSectionCard(
      leading: Icon(
        Icons.health_and_safety_outlined,
        color: Theme.of(context).colorScheme.primary,
      ),
      title: '记录状态',
      subtitle: '只展示真实采集、队列和服务器接收证据；无法确认时会明确显示未知。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_loading && view == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: JiYiSpacing.md),
              child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
            )
          else if (view != null) ...[
            JiYiStatusBanner(
              key: const ValueKey('recording-health-banner'),
              kind: _kind(view.status),
              title: _title(view.status),
              message: _message(view),
            ),
            const SizedBox(height: JiYiSpacing.sm),
            _CoverageSummary(view: view),
            if (view.activeGapReasons.isNotEmpty) ...[
              const SizedBox(height: JiYiSpacing.sm),
              Text(
                _activeGapMessage(view.activeGapReasons),
                key: const ValueKey('recording-health-gap-reason'),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
            if (_showQueue(view)) ...[
              const SizedBox(height: JiYiSpacing.sm),
              Text(
                _queueMessage(view),
                key: const ValueKey('recording-health-queue'),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
            if (view.lastFixAt != null || view.lastServerAckAt != null) ...[
              const SizedBox(height: JiYiSpacing.sm),
              Text(
                _lastSuccessMessage(view),
                key: const ValueKey('recording-health-last-success'),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
            if (action != null && _canRenderAction(action)) ...[
              const SizedBox(height: JiYiSpacing.sm),
              FilledButton.icon(
                key: const ValueKey('recording-health-action'),
                onPressed: _loading ? null : () => _runHealthAction(action),
                icon: Icon(_actionIcon(action)),
                label: Text(_actionLabel(action)),
              ),
            ],
          ],
          if (_error != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              message: _error!,
            ),
          ],
          const SizedBox(height: JiYiSpacing.sm),
          OutlinedButton.icon(
            key: const ValueKey('recording-health-refresh'),
            onPressed: _loading ? null : _refresh,
            icon: const Icon(Icons.refresh),
            label: Text(_loading ? '正在确认…' : '重新确认记录状态'),
          ),
        ],
      ),
    );
  }
}

class _CoverageSummary extends StatelessWidget {
  const _CoverageSummary({required this.view});

  final RecordingHealthView view;

  @override
  Widget build(BuildContext context) {
    final day = view.localDay ?? '今天';
    final coverage = switch (view.coverageState) {
      RecordingCoverageState.healthy => '证据覆盖较完整',
      RecordingCoverageState.partial => '只有部分时段有可靠证据',
      RecordingCoverageState.gapped => '存在已识别的记录间隔',
      RecordingCoverageState.unknown => '目前没有足够证据判断覆盖情况',
    };
    final covered = _durationText(view.coveredDurationSeconds);
    final gap = _durationText(view.knownGapDurationSeconds);
    final pauseOnly = !view.hasUnexplainedGap &&
        view.recentGapReasons.isNotEmpty &&
        view.recentGapReasons.every((reason) => reason == 'PRIVACY_PAUSED');

    final details = <String>[
      '$day：$coverage',
      if (view.coveredDurationSeconds > 0) '有证据支持的覆盖约 $covered',
      if (view.knownGapDurationSeconds > 0)
        pauseOnly ? '其中主动暂停约 $gap' : '已知间隔约 $gap',
    ];

    return Text(
      details.join('；'),
      key: const ValueKey('recording-health-coverage'),
      style: Theme.of(context).textTheme.bodyMedium,
    );
  }
}

JiYiStatusKind _kind(RecordingHealthStatus status) {
  return switch (status) {
    RecordingHealthStatus.healthy => JiYiStatusKind.success,
    RecordingHealthStatus.paused ||
    RecordingHealthStatus.recovering => JiYiStatusKind.info,
    RecordingHealthStatus.degraded ||
    RecordingHealthStatus.blocked => JiYiStatusKind.warning,
    RecordingHealthStatus.unknown => JiYiStatusKind.warning,
  };
}

String _title(RecordingHealthStatus status) {
  return switch (status) {
    RecordingHealthStatus.healthy => '当前自动记录正常',
    RecordingHealthStatus.degraded => '记录质量受限',
    RecordingHealthStatus.paused => '自动记录已暂停',
    RecordingHealthStatus.blocked => '自动记录当前受阻',
    RecordingHealthStatus.recovering => '正在恢复自动记录',
    RecordingHealthStatus.unknown => '当前记录状态未知',
  };
}

String _message(RecordingHealthView view) {
  return switch (view.reason) {
    'RECENT_CAPTURE_AND_ACK' => '最近的位置采集和服务器接收都已确认，当前没有明显积压。',
    'PRIVACY_PAUSED' => '这是你主动设置的隐私暂停，不会被当作意外记录故障。',
    'PERMISSION_BLOCKED' => '系统定位权限不足。请在下方“自动位置记忆”中按当前权限状态处理。',
    'LOCATION_SERVICES_OFF' => '系统定位服务已关闭；开启后再重新确认记录状态。',
    'AUTOMATIC_DISABLED' => '自动位置记忆当前关闭；只有你明确启用后才会开始后台记录。',
    'PLATFORM_RESTRICTED' => '系统当前限制后台运行，自动记录不能被确认正常。',
    'QUEUE_CAPACITY_PRESSURE' => '本机待处理记录接近容量上限或已有丢弃/存储异常。',
    'QUEUE_BACKLOG' || 'DELIVERY_BACKLOG' => '本机存在较久的待同步记录，当前不能视为完全正常。',
    'DELIVERY_FAILURE' => '最近同步连续失败，记录仍保留在本机队列等待恢复。',
    'RECOVERY_PENDING' => '系统正在等待恢复后台记录，恢复完成前不会显示为正常。',
    'PRODUCER_NOT_RUNNING' => '自动记录虽已配置，但本机后台采集当前没有运行。',
    'NO_RECENT_FIX' => '最近没有足够新的定位采集证据，无法确认持续记录正常。',
    'NO_RECENT_ACK' => '服务器最近没有确认收到位置记录，无法确认同步正常。',
    'RECORDED_GAP' => '今天的可靠证据之间存在未解释的记录间隔。',
    'CLIENT_STATE_STALE' => '本机状态已经过期，已按未知处理，不会沿用旧的正常状态。',
    'NATIVE_STATE_UNAVAILABLE' => view.nativeStateObserved
        ? '本机状态不可用，无法确认后台记录是否正常。'
        : '服务器能展示已接收的记录，但无法从这里确认这台手机当前的后台状态。',
    _ => '当前证据不足，无法确认自动记录是否正常。',
  };
}

String _activeGapMessage(List<String> reasons) {
  final labels = <String>[];
  for (final reason in reasons) {
    final label = switch (reason) {
      'PERMISSION_BLOCKED' => '定位权限阻断',
      'LOCATION_SERVICES_OFF' => '系统定位服务关闭',
      'PRIVACY_PAUSED' => '主动隐私暂停',
      'PLATFORM_RESTRICTED' => '系统后台限制',
      'QUEUE_CAPACITY_PRESSURE' => '本机队列容量压力',
      'DELIVERY_BACKLOG' => '同步积压',
      'PRODUCER_NOT_RUNNING' => '后台采集未运行',
      'NO_RECENT_FIX' => '缺少近期采集',
      'UNKNOWN' => '未解释的记录空档',
      _ => null,
    };
    if (label != null && !labels.contains(label)) labels.add(label);
  }
  return labels.isEmpty ? '当前存在记录空档。' : '当前诊断：${labels.join('、')}';
}

String _actionLabel(RecordingHealthAction action) {
  return switch (action) {
    RecordingHealthAction.requestForegroundPermission => '开启定位权限',
    RecordingHealthAction.enableAutomaticLocation => '允许后台定位',
    RecordingHealthAction.resumePrivacy => '恢复自动记录',
    RecordingHealthAction.startProducer => '重新启动自动记录',
    RecordingHealthAction.openLocationServicesSettings => '开启系统定位服务',
    RecordingHealthAction.openBackgroundLocationSettings => '前往系统设置允许始终定位',
  };
}

IconData _actionIcon(RecordingHealthAction action) {
  return switch (action) {
    RecordingHealthAction.requestForegroundPermission => Icons.location_on_outlined,
    RecordingHealthAction.enableAutomaticLocation => Icons.my_location_outlined,
    RecordingHealthAction.resumePrivacy => Icons.play_arrow_rounded,
    RecordingHealthAction.startProducer => Icons.restart_alt_rounded,
    RecordingHealthAction.openLocationServicesSettings => Icons.location_searching_outlined,
    RecordingHealthAction.openBackgroundLocationSettings => Icons.settings_outlined,
  };
}

bool _showQueue(RecordingHealthView view) {
  return view.totalQueueDepth > 0 ||
      view.capacityPressure ||
      view.deliveryFailureCount > 0;
}

String _queueMessage(RecordingHealthView view) {
  final parts = <String>[
    if (view.totalQueueDepth > 0) '待同步 ${view.totalQueueDepth} 条',
    if (view.capacityPressure) '队列容量压力较高',
    if (view.deliveryFailureCount > 0)
      '近期同步失败 ${view.deliveryFailureCount} 次',
  ];
  return parts.join(' · ');
}

String _lastSuccessMessage(RecordingHealthView view) {
  final parts = <String>[
    if (view.lastFixAt != null) '最近采集 ${_timeText(view.lastFixAt!)}',
    if (view.lastServerAckAt != null)
      '最近服务器确认 ${_timeText(view.lastServerAckAt!)}',
  ];
  return parts.join(' · ');
}

String _timeText(DateTime value) {
  final local = value.toLocal();
  String two(int number) => number.toString().padLeft(2, '0');
  return '${two(local.month)}-${two(local.day)} '
      '${two(local.hour)}:${two(local.minute)}';
}

String _durationText(int seconds) {
  if (seconds <= 0) return '0 分钟';
  final minutes = (seconds / 60).round();
  if (minutes < 60) return '$minutes 分钟';
  final hours = minutes ~/ 60;
  final remainder = minutes % 60;
  return remainder == 0 ? '$hours 小时' : '$hours 小时 $remainder 分钟';
}
