import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/native_location_bridge.dart';

void main() {
  test('typed native status parses CORE-001 queue and recovery diagnostics', () {
    final status = NativeLocationStatus.fromPlatform(<String, Object?>{
      'supported': true,
      'platform': 'android',
      'permission': 'background',
      'runtime': 'stopped',
      'automatic_enabled': true,
      'location_services_enabled': true,
      'restore_pending': true,
      'recovery_reason': 'boot_completed',
      'queue': <String, Object?>{
        'queue_schema_version': 2,
        'queue_depth': 812,
        'queue_capacity': 1000,
        'oldest_pending_at_millis': 1790820000000,
        'last_enqueue_at_millis': 1790820300000,
        'last_delivery_at_millis': 1790819000000,
        'delivery_failure_count': 3,
        'last_delivery_failure_at_millis': 1790820100000,
        'last_delivery_failure_reason': 'network_unavailable',
        'capacity_pressure': true,
        'dropped_sample_count': 2,
        'last_drop_at_millis': 1790820200000,
        'last_drop_reason': 'native_queue_capacity',
        'queue_corrupt': false,
      },
    });

    expect(status.restorePending, isTrue);
    expect(status.recoveryReason, 'boot_completed');
    expect(status.queue.schemaVersion, 2);
    expect(status.queue.depth, 812);
    expect(status.queue.capacity, 1000);
    expect(status.queue.capacityPressure, isTrue);
    expect(status.queue.deliveryFailureCount, 3);
    expect(status.queue.lastDeliveryFailureReason, 'network_unavailable');
    expect(status.queue.droppedSampleCount, 2);
    expect(status.queue.lastDropReason, 'native_queue_capacity');
    expect(status.queue.oldestPendingAt, isNotNull);
    expect(status.queue.corrupt, isFalse);
  });

  test('missing V2 diagnostics fail closed to an empty typed queue', () {
    final status = NativeLocationStatus.fromPlatform(<String, Object?>{
      'supported': true,
      'platform': 'ios',
      'permission': 'background',
      'runtime': 'running',
      'automatic_enabled': true,
      'location_services_enabled': true,
    });

    expect(status.queue.depth, 0);
    expect(status.queue.capacity, 0);
    expect(status.queue.capacityPressure, isFalse);
    expect(status.queue.corrupt, isFalse);
    expect(status.restorePending, isFalse);
  });
}
