import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/recording_health.dart';

Map<String, dynamic> _protocolResponse({
  String status = 'UNKNOWN',
  String? reason,
  bool automatic = true,
  String? permission = 'BACKGROUND',
  String? services = 'ON',
  String? background = 'ELIGIBLE',
  List<String> activeGaps = const <String>[],
}) {
  final resolvedReason = reason ??
      switch (status) {
        'HEALTHY' => 'RECENT_CAPTURE_AND_ACK',
        'PAUSED' => 'PRIVACY_PAUSED',
        _ => 'NATIVE_STATE_UNAVAILABLE',
      };
  return <String, dynamic>{
    'health': <String, dynamic>{
      'status': status,
      'status_reason': resolvedReason,
      'automatic_enabled': automatic,
      'privacy_paused': status == 'PAUSED',
      'permission_state': permission,
      'location_services_state': services,
      'background_runtime_state': background,
      'battery_optimization_state': 'OPTIMIZED',
      'native_producer_state': 'RUNNING',
      'native_queue_depth': 0,
      'native_queue_capacity': 1000,
      'native_oldest_pending_at': null,
      'sqlite_queue_depth': 0,
      'capacity_pressure': false,
      'last_fix_at': status == 'HEALTHY' ? '2026-10-01T10:00:00Z' : null,
      'last_enqueue_at': null,
      'last_handoff_at': null,
      'last_upload_attempt_at': null,
      'last_upload_success_at': null,
      'last_server_ack_at':
          status == 'HEALTHY' ? '2026-10-01T10:01:00Z' : null,
      'last_visit_at': null,
      'delivery_failure_count': 0,
      'last_delivery_error_code': null,
      'recovery_pending': status == 'RECOVERING',
      'recording_gap_state': status == 'HEALTHY' ? 'NONE' : 'UNKNOWN',
      'updated_at': '2026-10-01T10:02:00Z',
    },
    'today': <String, dynamic>{
      'local_day': '2026-10-01',
      'timezone': 'Asia/Shanghai',
      'first_observed_at': null,
      'last_observed_at': null,
      'trusted_location_sample_count': 0,
      'visit_count': 0,
      'memory_count': 0,
      'covered_duration_seconds': 0,
      'known_gap_duration_seconds': 0,
      'largest_known_gap_seconds': 0,
      'coverage_state': 'UNKNOWN',
      'has_capacity_pressure': false,
      'has_recorded_gap': false,
      'has_unexplained_gap': false,
      'recent_gaps': <Object?>[],
    },
    'aggregates': <String, dynamic>{
      'healthy_days_7d': 0,
      'healthy_days_30d': 0,
      'evidence_days_7d': 0,
      'evidence_days_30d': 0,
      'gap_hours_7d': null,
      'gap_hours_30d': null,
      'bounded_gap_hours_7d': 0.0,
      'bounded_gap_hours_30d': 0.0,
      'days_with_capacity_pressure': null,
      'days_with_permission_block': null,
      'current_capacity_pressure': false,
      'current_permission_block': false,
    },
    'recent_gaps': <Object?>[],
    'active_gap_reasons': activeGaps,
    'server_observed_at': '2026-10-01T10:02:00Z',
    'native_state_observed': true,
  };
}

void main() {
  test('recording health parser covers all states and fails malformed closed', () {
    final expected = <String, RecordingHealthStatus>{
      'HEALTHY': RecordingHealthStatus.healthy,
      'DEGRADED': RecordingHealthStatus.degraded,
      'PAUSED': RecordingHealthStatus.paused,
      'BLOCKED': RecordingHealthStatus.blocked,
      'RECOVERING': RecordingHealthStatus.recovering,
      'UNKNOWN': RecordingHealthStatus.unknown,
    };
    for (final entry in expected.entries) {
      final parsed = RecordingHealthView.fromJson(
        _protocolResponse(status: entry.key),
      );
      expect(parsed.status, entry.value);
      expect(parsed.malformed, isFalse);
    }

    final missingRequired = _protocolResponse(status: 'HEALTHY');
    (missingRequired['health'] as Map<String, dynamic>)
        .remove('native_queue_depth');
    final missingParsed = RecordingHealthView.fromJson(missingRequired);
    expect(missingParsed.status, RecordingHealthStatus.unknown);
    expect(missingParsed.malformed, isTrue);

    final invalidRequired = _protocolResponse(status: 'HEALTHY');
    (invalidRequired['health'] as Map<String, dynamic>)['capacity_pressure'] =
        'false';
    final invalidParsed = RecordingHealthView.fromJson(invalidRequired);
    expect(invalidParsed.status, RecordingHealthStatus.unknown);
    expect(invalidParsed.malformed, isTrue);
  });

  test('reason-specific CTA is derived only from proven authority', () {
    RecordingHealthView parse({
      required String reason,
      bool automatic = true,
      String? permission = 'BACKGROUND',
      String? services = 'ON',
      String? background = 'ELIGIBLE',
      List<String> activeGaps = const <String>[],
    }) {
      return RecordingHealthView.fromJson(
        _protocolResponse(
          status: reason == 'PRIVACY_PAUSED' ? 'PAUSED' : 'BLOCKED',
          reason: reason,
          automatic: automatic,
          permission: permission,
          services: services,
          background: background,
          activeGaps: activeGaps,
        ),
      );
    }

    expect(
      parse(reason: 'PERMISSION_BLOCKED', permission: 'NOT_DETERMINED')
          .suggestedAction,
      RecordingHealthAction.requestForegroundPermission,
    );
    expect(
      parse(reason: 'PERMISSION_BLOCKED', permission: 'FOREGROUND')
          .suggestedAction,
      RecordingHealthAction.enableAutomaticLocation,
    );
    expect(
      parse(reason: 'PERMISSION_BLOCKED', permission: 'RESTRICTED')
          .suggestedAction,
      isNull,
    );
    expect(
      parse(reason: 'PRIVACY_PAUSED').suggestedAction,
      RecordingHealthAction.resumePrivacy,
    );
    expect(
      parse(reason: 'LOCATION_SERVICES_OFF', services: 'OFF').suggestedAction,
      RecordingHealthAction.openLocationServicesSettings,
    );
    expect(
      parse(reason: 'PLATFORM_RESTRICTED', background: 'RESTRICTED')
          .suggestedAction,
      isNull,
    );
    final capacity = parse(
      reason: 'QUEUE_CAPACITY_PRESSURE',
      activeGaps: const <String>['QUEUE_CAPACITY_PRESSURE'],
    );
    expect(capacity.suggestedAction, isNull);
    expect(capacity.activeGapReasons, const <String>['QUEUE_CAPACITY_PRESSURE']);
  });

  test('client projection is privacy-safe and bounds raw failures', () {
    final native = NativeLocationStatus(
      supported: true,
      platform: 'android',
      permission: NativeLocationPermission.background,
      runtime: NativeLocationRuntime.running,
      automaticEnabled: true,
      locationServicesEnabled: true,
      backgroundRuntimeState: NativeBackgroundRuntimeState.eligible,
      batteryOptimizationState: NativeBatteryOptimizationState.optimized,
      lastFixAt: DateTime.utc(2026, 10, 1, 10),
      restorePending: false,
      queue: NativeLocationQueueDiagnostics(
        schemaVersion: 2,
        depth: 3,
        capacity: 1000,
        deliveryFailureCount: 1,
        capacityPressure: false,
        droppedSampleCount: 0,
        corrupt: false,
        storageUnavailable: false,
        lastEnqueueAt: DateTime.utc(2026, 10, 1, 10, 1),
        lastDeliveryAt: DateTime.utc(2026, 10, 1, 10, 2),
        lastDeliveryFailureReason: 'Socket timeout with private body data',
      ),
    );
    final sqlite = LocationQueueDiagnostics(
      queueDepth: 2,
      blockedCount: 0,
      queueCapacity: 1000,
      capacityPressure: false,
      deliveryFailureCount: 2,
      lastEnqueueAt: DateTime.utc(2026, 10, 1, 10, 3),
      lastAttemptAt: DateTime.utc(2026, 10, 1, 10, 4),
      lastDeliveryAt: DateTime.utc(2026, 10, 1, 10, 5),
      lastFailureReason: 'raw server response must not leave device',
    );

    final payload = buildRecordingHealthClientState(
      status: native,
      sqliteQueue: sqlite,
      observedAt: DateTime.utc(2026, 10, 1, 10, 6),
    )!;

    expect(payload['permission_state'], 'BACKGROUND');
    expect(payload['background_runtime_state'], 'ELIGIBLE');
    expect(payload['battery_optimization_state'], 'OPTIMIZED');
    expect(payload['native_producer_state'], 'RUNNING');
    expect(payload['native_queue_schema_version'], 2);
    expect(payload['last_delivery_error_code'], 'NETWORK_UNAVAILABLE');
    expect(payload['delivery_failure_count'], 3);
    expect(payload['last_upload_attempt_at'], '2026-10-01T10:04:00.000Z');

    expect(payload.containsKey('user_id'), isFalse);
    expect(payload.containsKey('device_id'), isFalse);
    expect(payload.containsKey('latitude'), isFalse);
    expect(payload.containsKey('longitude'), isFalse);
    expect(payload.containsKey('content'), isFalse);
    expect(payload.toString(), isNot(contains('private body data')));
    expect(payload.toString(), isNot(contains('raw server response')));
  });

  test('unsupported native bridge produces no client authority payload', () {
    final payload = buildRecordingHealthClientState(
      status: const NativeLocationStatus.unavailable(),
      sqliteQueue: const LocationQueueDiagnostics(
        queueDepth: 0,
        blockedCount: 0,
        deliveryFailureCount: 0,
      ),
    );
    expect(payload, isNull);
  });
}
