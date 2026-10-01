import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api_client.dart';
import 'native_location_bridge.dart';
import 'native_motion_sampling_bridge.dart';
import 'offline_queue.dart';
import 'passive_memory_delivery.dart';
import 'stage1_app.dart';
export 'stage1_app.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const JiYiApp());
}

/// Android WorkManager invokes this headless entry point after reboot/process recovery.
///
/// Native recovery only schedules this isolate; it never starts location production itself.
/// This isolate must first restore/refresh AUTH-001, then fetch fresh server Privacy through
/// [PassiveMemoryDeliveryCoordinator] before any producer resume or location upload.
@pragma('vm:entry-point')
Future<void> passiveMemoryRecoveryMain() async {
  WidgetsFlutterBinding.ensureInitialized();
  const completion = MethodChannel('cn.jiyidashi/passive_recovery');
  final api = JiYiApiClient();
  final store = OfflineQueueStore();
  final location = MethodChannelNativeLocationBridge();
  final sampling = MethodChannelNativeMotionSamplingBridge();

  var retry = false;
  String status = 'unexpected_failure';
  try {
    final report = await PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    ).recoverAndDeliver(
      restoreSessionIfNeeded: true,
      allowProducerResume: true,
    );
    status = report.status.name;
    retry = switch (report.status) {
      PassiveMemoryRecoveryStatus.serverUnavailable ||
      PassiveMemoryRecoveryStatus.privacyUnavailable ||
      PassiveMemoryRecoveryStatus.retryableFailure ||
      PassiveMemoryRecoveryStatus.nativeUnavailable => true,
      _ => false,
    };
  } catch (_) {
    // The native worker receives only a bounded retry decision, never exception text that
    // could accidentally include auth/session material.
    retry = true;
  } finally {
    await store.close();
    await sampling.close();
    try {
      await completion.invokeMethod<void>(
        'complete',
        <String, Object?>{
          'status': status,
          'retry': retry,
        },
      );
    } on PlatformException {
      // Worker timeout/retry remains the native fail-safe if completion cannot be delivered.
    } on MissingPluginException {
      // Same fail-safe.
    }
  }
}
