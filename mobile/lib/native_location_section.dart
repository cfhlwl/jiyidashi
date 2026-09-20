import 'package:flutter/material.dart';

import 'native_location_bridge.dart';
import 'native_location_controller.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

// 此组件只是 controller 状态的展示与“显式用户操作”入口，不是第二套定位生命周期状态机。
// 权限、自动定位授权与原生 producer 是否运行都由 controller/native bridge 决定；build/refresh 绝不能隐式申请权限或启动采集。
class NativeLocationSection extends StatefulWidget {
  const NativeLocationSection({
    super.key,
    required this.controller,
  });

  final NativeLocationController controller;

  @override
  State<NativeLocationSection> createState() => _NativeLocationSectionState();
}

class _NativeLocationSectionState extends State<NativeLocationSection> {
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
  }

  @override
  void didUpdateWidget(covariant NativeLocationSection oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_changed);
      widget.controller.addListener(_changed);
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_changed);
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final status = controller.status;
    final privacyGate = controller.privacyGate;
    final privacyActive = privacyGate == NativeLocationPrivacyGate.active;
    final privacyPaused = privacyGate == NativeLocationPrivacyGate.paused;

    return JiYiSectionCard(
      leading: Icon(
        Icons.location_on_outlined,
        color: Theme.of(context).colorScheme.primary,
      ),
      title: '自动位置记忆',
      subtitle: '默认关闭。前台权限先行；只有你明确启用后才会申请后台定位。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!privacyActive)
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              title: privacyPaused ? '自动采集已暂停' : '正在确认隐私状态',
              message: privacyPaused
                  ? '隐私暂停期间不会启动原生位置采集。恢复记录后也不会静默提升定位权限。'
                  : '隐私状态未知时按停止处理，不会自动采集位置。',
            )
          else if (status == null)
            const JiYiStatusBanner(
              kind: JiYiStatusKind.info,
              title: '正在读取系统定位状态',
              message: '读取状态不会请求权限，也不会启动定位。',
            )
          else if (!status.supported)
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              title: '当前设备暂不可用',
              message: _reasonMessage(status.reason),
            )
          else
            _NativeLocationStatusView(status: status),
          if (controller.error != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: JiYiStatusKind.error,
              message: controller.error!,
            ),
          ],
          const SizedBox(height: JiYiSpacing.md),
          // 只有隐私 gate 明确 active 时才呈现权限/启用/启动操作；这些状态迁移均来自用户点击，
          // 单纯观察到系统权限或重建 UI 不代表用户同意自动采集。
          if (privacyActive && status != null && status.supported) ...[
            if (!status.hasForegroundPermission)
              FilledButton.icon(
                key: const ValueKey('location-request-foreground'),
                onPressed: controller.busy
                    ? null
                    : () => controller.requestForegroundPermission(),
                icon: const Icon(Icons.location_searching_outlined),
                label: const Text('先允许使用时定位'),
              )
            else if (!status.automaticEnabled &&
                status.reason == 'background_settings_required')
              FilledButton.icon(
                key: const ValueKey('location-open-background-settings'),
                onPressed: controller.busy
                    ? null
                    : () => controller.openBackgroundLocationSettings(),
                icon: const Icon(Icons.settings_outlined),
                label: const Text('前往系统设置允许始终定位'),
              )
            else if (!status.automaticEnabled)
              FilledButton.icon(
                key: const ValueKey('location-enable-automatic'),
                onPressed: controller.busy
                    ? null
                    : () => controller.enableAutomaticLocation(),
                icon: const Icon(Icons.my_location_outlined),
                label: const Text('启用自动位置记忆'),
              )
            else if (status.runtime != NativeLocationRuntime.running)
              FilledButton.icon(
                key: const ValueKey('location-start'),
                onPressed: controller.busy ? null : () => controller.start(),
                icon: const Icon(Icons.play_arrow_rounded),
                label: const Text('启动自动位置记忆'),
              ),
          ],
          if (status?.automaticEnabled == true) ...[
            const SizedBox(height: JiYiSpacing.xs),
            OutlinedButton.icon(
              key: const ValueKey('location-disable-automatic'),
              onPressed: controller.busy
                  ? null
                  : () => controller.disableAutomaticLocation(),
              icon: const Icon(Icons.location_disabled_outlined),
              label: const Text('关闭自动位置记忆'),
            ),
          ],
          const SizedBox(height: JiYiSpacing.xs),
          TextButton.icon(
            key: const ValueKey('location-refresh-status'),
            onPressed: controller.busy ? null : () => controller.refresh(),
            icon: const Icon(Icons.refresh),
            label: const Text('刷新系统定位状态'),
          ),
        ],
      ),
    );
  }
}

class _NativeLocationStatusView extends StatelessWidget {
  const _NativeLocationStatusView({required this.status});

  final NativeLocationStatus status;

  @override
  Widget build(BuildContext context) {
    final running = status.runtime == NativeLocationRuntime.running;
    final paused = status.runtime == NativeLocationRuntime.paused;
    final kind = running
        ? JiYiStatusKind.success
        : (paused ? JiYiStatusKind.warning : JiYiStatusKind.info);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        JiYiStatusBanner(
          kind: kind,
          title: running
              ? '自动位置记忆正在运行'
              : (paused ? '原生位置采集已暂停' : '原生位置采集未运行'),
          message: _reasonMessage(status.reason),
        ),
        const SizedBox(height: JiYiSpacing.sm),
        Wrap(
          spacing: JiYiSpacing.xs,
          runSpacing: JiYiSpacing.xs,
          children: [
            Chip(label: Text('权限：${_permissionLabel(status.permission)}')),
            Chip(
              label: Text(
                status.automaticEnabled ? '自动位置：已启用' : '自动位置：未启用',
              ),
            ),
            Chip(
              label: Text(
                status.locationServicesEnabled ? '系统定位：开启' : '系统定位：关闭',
              ),
            ),
          ],
        ),
        if (status.lastFixAt != null) ...[
          const SizedBox(height: JiYiSpacing.xs),
          Text(
            status.lastAccuracyMeters == null
                ? '最近收到系统位置更新：${status.lastFixAt!.toLocal()}'
                : '最近收到系统位置更新：${status.lastFixAt!.toLocal()} · 精度约 ${status.lastAccuracyMeters!.round()} 米',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ],
    );
  }
}

String _permissionLabel(NativeLocationPermission permission) {
  return switch (permission) {
    NativeLocationPermission.notDetermined => '未询问',
    NativeLocationPermission.foreground => '仅使用时',
    NativeLocationPermission.background => '允许后台',
    NativeLocationPermission.denied => '已拒绝',
    NativeLocationPermission.restricted => '系统受限',
    NativeLocationPermission.unknown => '未知',
  };
}

String _reasonMessage(String? reason) {
  return switch (reason) {
    'foreground_permission_requested' => '已向系统请求“使用时定位”，请按系统提示选择。',
    'foreground_permission_required' => '请先允许“使用时定位”，再决定是否启用自动位置记忆。',
    'background_permission_requested' => '已请求后台定位授权；系统确认后请刷新状态。',
    'background_settings_required' =>
      'Android 11 及更高版本需要你在系统设置中手动选择“始终允许”。返回 App 后只会检查系统授权，不会自动提升权限。',
    'background_permission_required' => '后台定位尚未授权。只有明确启用自动位置记忆后才会申请。',
    'permission_denied' => '系统定位权限已拒绝或撤销，原生采集保持停止。',
    'location_services_disabled' => '系统定位服务已关闭，原生采集保持停止。',
    'automatic_location_disabled' => '自动位置记忆当前关闭。',
    'owner_mismatch' => '当前账号没有这台设备上的自动位置授权。',
    'paused' => '隐私暂停已生效，原生位置采集已停止。',
    'native_start_failed' => '系统未能启动位置服务，请刷新状态后重试。',
    'native_bridge_unavailable' => '当前系统没有可用的原生位置 Bridge。',
    'native_bridge_error' => '读取原生位置状态失败，已按停止处理。',
    null => '状态正常。',
    _ => '当前保持 fail-closed；请刷新系统定位状态。',
  };
}
