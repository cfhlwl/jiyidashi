import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/recording_health.dart';

void main() {
  test('recording health parser covers all states and fails malformed closed', () {
    Map<String, dynamic> response(String status) => <String, dynamic>{
          'health': <String, dynamic>{
            'status': status,
            'status_reason': status == 'HEALTHY'
                ? 'RECENT_CAPTURE_AND_ACK'
                : 'NATIVE_STATE_UNAVAILABLE',
            'privacy_paused': status == 'PAUSED',
            'native_queue_depth': 0,
            'sqlite_queue_depth': 0,
            'capacity_pressure': false,
            'delivery_failure_count': 0,
            'recovery_pending': status == 'RECOVERING',
            'last_fix_at': null,
            'last_server_ack_at': null,
          },
          'today': <String, dynamic>{
            'local_day': '2026-10-01',
            'timezone': 'Asia/Shanghai',
            'covered_duration_seconds': 0,
            'known_gap_duration_seconds': 0,
            'has_recorded_gap': false,
            'coverage_state': 'UNKNOWN',
          },
          'recent_gaps': <Object?>[],
          'native_state_observed': true,
        };

    final expected = <String, RecordingHealthStatus>{
      'HEALTHY': RecordingHealthStatus.healthy,
      'DEGRADED': RecordingHealthStatus.degraded,
      'PAUSED': RecordingHealthStatus.paused,
      'BLOCKED': RecordingHealthStatus.blocked,
      'RECOVERING': RecordingHealthStatus.recovering,
      'UNKNOWN': RecordingHealthStatus.unknown,
    };
    for (final entry in expected.entries) {
      final parsed = RecordingHealthView.fromJson(response(entry.key));
      expect(parsed.status, entry.value);
      expect(parsed.malformed, isFalse);
    }

    final malformed = RecordingHealthView.fromJson(<String, dynamic>{
      'health': <String, dynamic>{'status': 'HEALTHY'},
    });
    expect(malformed.status, RecordingHealthStatus.unknown);
    expect(malformed.malformed, isTrue);
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
      return RecordingHealthView.fromJson(<String, dynamic>{
        'health': <String, dynamic>{
          'status': reason == 'PRIVACY_PAUSED' ? 'PAUSED' : 'BLOCKED',
          'status_reason': reason,
          'automatic_enabled': automatic,
          'privacy_paused': reason == 'PRIVACY_PAUSED',
          'permission_state': permission,
          'location_services_state': services,
          'background_runtime_state': background,
          'native_queue_depth': 0,
          'sqlite_queue_depth': 0,
          'capacity_pressure': false,
          'delivery_failure_count': 0,
          'recovery_pending': false,
          'last_fix_at': null,
          'last_server_ack_at': null,
        },
        'today': <String, dynamic>{
          'local_day': '2026-10-01',
          'timezone': 'Asia/Shanghai',
          'covered_duration_seconds': 0,
          'known_gap_duration_seconds': 0,
          'has_recorded_gap': false,
          'coverage_state': 'UNKNOWN',
        },
        'recent_gaps': <Object?>[],
        'active_gap_reasons': activeGaps,
        'native_state_observed': true,
      });
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
      RecordingHealthAction.recheckLocationServices,
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
