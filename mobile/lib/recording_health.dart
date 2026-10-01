import 'native_location_bridge.dart';
import 'offline_queue.dart';

enum RecordingHealthStatus {
  healthy,
  degraded,
  paused,
  blocked,
  recovering,
  unknown,
}

enum RecordingCoverageState {
  healthy,
  partial,
  gapped,
  unknown,
}

enum RecordingHealthAction {
  requestForegroundPermission,
  enableAutomaticLocation,
  resumePrivacy,
  startProducer,
  openLocationServicesSettings,
  openBackgroundLocationSettings,
}

class RecordingHealthView {
  const RecordingHealthView({
    required this.status,
    required this.reason,
    required this.privacyPaused,
    required this.nativeStateObserved,
    required this.automaticEnabled,
    required this.permissionState,
    required this.locationServicesState,
    required this.backgroundRuntimeState,
    required this.coverageState,
    required this.localDay,
    required this.timezone,
    required this.coveredDurationSeconds,
    required this.knownGapDurationSeconds,
    required this.hasRecordedGap,
    required this.hasUnexplainedGap,
    required this.nativeQueueDepth,
    required this.sqliteQueueDepth,
    required this.capacityPressure,
    required this.deliveryFailureCount,
    required this.recoveryPending,
    required this.malformed,
    this.lastFixAt,
    this.lastServerAckAt,
    this.recentGapReasons = const <String>[],
    this.activeGapReasons = const <String>[],
  });

  const RecordingHealthView.unknown({this.reason = 'MALFORMED_RESPONSE'})
      : status = RecordingHealthStatus.unknown,
        privacyPaused = false,
        nativeStateObserved = false,
        automaticEnabled = null,
        permissionState = null,
        locationServicesState = null,
        backgroundRuntimeState = null,
        coverageState = RecordingCoverageState.unknown,
        localDay = null,
        timezone = null,
        coveredDurationSeconds = 0,
        knownGapDurationSeconds = 0,
        hasRecordedGap = false,
        hasUnexplainedGap = false,
        nativeQueueDepth = 0,
        sqliteQueueDepth = 0,
        capacityPressure = false,
        deliveryFailureCount = 0,
        recoveryPending = false,
        malformed = true,
        lastFixAt = null,
        lastServerAckAt = null,
        recentGapReasons = const <String>[],
        activeGapReasons = const <String>[];

  final RecordingHealthStatus status;
  final String reason;
  final bool privacyPaused;
  final bool nativeStateObserved;
  final bool? automaticEnabled;
  final String? permissionState;
  final String? locationServicesState;
  final String? backgroundRuntimeState;
  final RecordingCoverageState coverageState;
  final String? localDay;
  final String? timezone;
  final int coveredDurationSeconds;
  final int knownGapDurationSeconds;
  final bool hasRecordedGap;
  final bool hasUnexplainedGap;
  final int nativeQueueDepth;
  final int sqliteQueueDepth;
  final bool capacityPressure;
  final int deliveryFailureCount;
  final bool recoveryPending;
  final DateTime? lastFixAt;
  final DateTime? lastServerAckAt;
  final List<String> recentGapReasons;
  final List<String> activeGapReasons;
  final bool malformed;

  int get totalQueueDepth => nativeQueueDepth + sqliteQueueDepth;

  RecordingHealthAction? get suggestedAction {
    if (reason == 'PRIVACY_PAUSED') {
      return RecordingHealthAction.resumePrivacy;
    }
    if (reason == 'AUTOMATIC_DISABLED') {
      return RecordingHealthAction.enableAutomaticLocation;
    }
    if (reason == 'LOCATION_SERVICES_OFF') {
      return RecordingHealthAction.openLocationServicesSettings;
    }
    if (reason == 'PERMISSION_BLOCKED') {
      return switch (permissionState) {
        'FOREGROUND' => RecordingHealthAction.enableAutomaticLocation,
        'NOT_DETERMINED' || 'DENIED' =>
          RecordingHealthAction.requestForegroundPermission,
        _ => null,
      };
    }
    if (reason == 'PRODUCER_NOT_RUNNING' &&
        automaticEnabled == true &&
        permissionState == 'BACKGROUND' &&
        locationServicesState == 'ON' &&
        backgroundRuntimeState == 'ELIGIBLE') {
      return RecordingHealthAction.startProducer;
    }
    return null;
  }

  factory RecordingHealthView.fromJson(Map<String, dynamic> raw) {
    try {
      final health = _stringMap(raw['health']);
      final today = _stringMap(raw['today']);
      if (health == null || today == null) {
        return const RecordingHealthView.unknown();
      }
      final status = _parseHealthStatus(health['status']?.toString());
      final coverage = _parseCoverageState(today['coverage_state']?.toString());
      final localDay = today['local_day']?.toString();
      final timezone = today['timezone']?.toString();
      if (localDay == null ||
          localDay.isEmpty ||
          timezone == null ||
          timezone.isEmpty) {
        return const RecordingHealthView.unknown();
      }

      final gaps = <String>[];
      final rawGaps = raw['recent_gaps'];
      if (rawGaps is List) {
        for (final item in rawGaps.take(8)) {
          final gap = _stringMap(item);
          final reason = gap?['reason']?.toString();
          if (reason != null && reason.isNotEmpty) gaps.add(reason);
        }
      }

      final activeGaps = <String>[];
      final rawActiveGaps = raw['active_gap_reasons'];
      if (rawActiveGaps is List) {
        for (final item in rawActiveGaps.take(8)) {
          final reason = item?.toString();
          if (reason != null && reason.isNotEmpty) activeGaps.add(reason);
        }
      }

      return RecordingHealthView(
        status: status,
        reason: health['status_reason']?.toString() ?? 'UNKNOWN',
        privacyPaused: health['privacy_paused'] == true,
        nativeStateObserved: raw['native_state_observed'] == true,
        automaticEnabled: health['automatic_enabled'] is bool
            ? health['automatic_enabled'] as bool
            : null,
        permissionState: health['permission_state']?.toString(),
        locationServicesState: health['location_services_state']?.toString(),
        backgroundRuntimeState: health['background_runtime_state']?.toString(),
        coverageState: coverage,
        localDay: localDay,
        timezone: timezone,
        coveredDurationSeconds: _nonNegativeInt(today['covered_duration_seconds']),
        knownGapDurationSeconds:
            _nonNegativeInt(today['known_gap_duration_seconds']),
        hasRecordedGap: today['has_recorded_gap'] == true,
        hasUnexplainedGap: today['has_unexplained_gap'] == true,
        nativeQueueDepth: _nonNegativeInt(health['native_queue_depth']),
        sqliteQueueDepth: _nonNegativeInt(health['sqlite_queue_depth']),
        capacityPressure: health['capacity_pressure'] == true,
        deliveryFailureCount:
            _nonNegativeInt(health['delivery_failure_count']),
        recoveryPending: health['recovery_pending'] == true,
        lastFixAt: _date(health['last_fix_at']),
        lastServerAckAt: _date(health['last_server_ack_at']),
        recentGapReasons: gaps,
        activeGapReasons: activeGaps,
        malformed: false,
      );
    } catch (_) {
      return const RecordingHealthView.unknown();
    }
  }

  static Map<String, dynamic>? _stringMap(Object? value) {
    if (value is! Map) return null;
    return value.map<String, dynamic>(
      (key, item) => MapEntry(key.toString(), item),
    );
  }

  static int _nonNegativeInt(Object? value) {
    final parsed = value is num
        ? value.toInt()
        : int.tryParse(value?.toString() ?? '');
    if (parsed == null || parsed < 0) return 0;
    return parsed;
  }

  static DateTime? _date(Object? value) {
    if (value == null) return null;
    return DateTime.tryParse(value.toString())?.toUtc();
  }

  static RecordingHealthStatus _parseHealthStatus(String? value) {
    return switch (value) {
      'HEALTHY' => RecordingHealthStatus.healthy,
      'DEGRADED' => RecordingHealthStatus.degraded,
      'PAUSED' => RecordingHealthStatus.paused,
      'BLOCKED' => RecordingHealthStatus.blocked,
      'RECOVERING' => RecordingHealthStatus.recovering,
      _ => RecordingHealthStatus.unknown,
    };
  }

  static RecordingCoverageState _parseCoverageState(String? value) {
    return switch (value) {
      'HEALTHY' => RecordingCoverageState.healthy,
      'PARTIAL' => RecordingCoverageState.partial,
      'GAPPED' => RecordingCoverageState.gapped,
      _ => RecordingCoverageState.unknown,
    };
  }
}

Map<String, dynamic>? buildRecordingHealthClientState({
  required NativeLocationStatus status,
  required LocationQueueDiagnostics sqliteQueue,
  DateTime? observedAt,
}) {
  if (!status.supported) return null;

  String permission() {
    return switch (status.permission) {
      NativeLocationPermission.background => 'BACKGROUND',
      NativeLocationPermission.foreground => 'FOREGROUND',
      NativeLocationPermission.denied => 'DENIED',
      NativeLocationPermission.restricted => 'RESTRICTED',
      NativeLocationPermission.notDetermined => 'NOT_DETERMINED',
      NativeLocationPermission.unknown => 'UNKNOWN',
    };
  }

  String runtime() {
    return switch (status.runtime) {
      NativeLocationRuntime.running => 'RUNNING',
      NativeLocationRuntime.paused => 'PAUSED',
      NativeLocationRuntime.stopped => 'STOPPED',
    };
  }

  String backgroundRuntime() {
    return switch (status.backgroundRuntimeState) {
      NativeBackgroundRuntimeState.eligible => 'ELIGIBLE',
      NativeBackgroundRuntimeState.restricted => 'RESTRICTED',
      NativeBackgroundRuntimeState.unknown => 'UNKNOWN',
    };
  }

  String batteryOptimization() {
    return switch (status.batteryOptimizationState) {
      NativeBatteryOptimizationState.exempt => 'EXEMPT',
      NativeBatteryOptimizationState.optimized => 'OPTIMIZED',
      NativeBatteryOptimizationState.notApplicable => 'NOT_APPLICABLE',
      NativeBatteryOptimizationState.unknown => 'UNKNOWN',
    };
  }

  String? boundedDeliveryError() {
    final source =
        status.queue.lastDeliveryFailureReason ?? sqliteQueue.lastFailureReason;
    if (source == null || source.trim().isEmpty) return null;
    final normalized = source.toLowerCase();
    if (normalized.contains('network') ||
        normalized.contains('timeout') ||
        normalized.contains('socket') ||
        normalized.contains('offline')) {
      return 'NETWORK_UNAVAILABLE';
    }
    if (normalized.contains('privacy') || normalized.contains('paused')) {
      return 'PRIVACY_REJECTED';
    }
    if (normalized.contains('auth') ||
        normalized.contains('owner') ||
        normalized.contains('session') ||
        normalized.contains('401')) {
      return 'AUTHORITY_REJECTED';
    }
    if (normalized.contains('queue') ||
        normalized.contains('storage') ||
        normalized.contains('capacity')) {
      return 'QUEUE_ERROR';
    }
    if (normalized.contains('protocol') ||
        normalized.contains('400') ||
        normalized.contains('409') ||
        normalized.contains('422')) {
      return 'PROTOCOL_ERROR';
    }
    if (normalized.contains('server') ||
        normalized.contains('429') ||
        normalized.contains('500') ||
        normalized.contains('502') ||
        normalized.contains('503')) {
      return 'SERVER_RETRYABLE';
    }
    return 'UNKNOWN';
  }

  DateTime? newest(DateTime? a, DateTime? b) {
    if (a == null) return b;
    if (b == null) return a;
    return a.isAfter(b) ? a : b;
  }

  String? timestamp(DateTime? value) => value?.toUtc().toIso8601String();
  final failureCount =
      (status.queue.deliveryFailureCount + sqliteQueue.deliveryFailureCount)
          .clamp(0, 100000);

  return <String, dynamic>{
    'observed_at': (observedAt ?? DateTime.now()).toUtc().toIso8601String(),
    'platform': status.platform,
    'automatic_enabled': status.automaticEnabled,
    'permission_state': permission(),
    'location_services_state': status.locationServicesEnabled ? 'ON' : 'OFF',
    'background_runtime_state': backgroundRuntime(),
    'battery_optimization_state': batteryOptimization(),
    'native_producer_state': runtime(),
    'native_queue_schema_version': status.queue.schemaVersion,
    'native_queue_depth': status.queue.depth,
    'native_queue_capacity': status.queue.capacity,
    'native_oldest_pending_at': timestamp(status.queue.oldestPendingAt),
    'native_queue_corrupt': status.queue.corrupt,
    'native_queue_storage_unavailable': status.queue.storageUnavailable,
    'sqlite_queue_depth': sqliteQueue.queueDepth,
    'sqlite_oldest_pending_at': timestamp(sqliteQueue.oldestPendingAt),
    'capacity_pressure':
        status.queue.capacityPressure || sqliteQueue.capacityPressure,
    'dropped_sample_count': status.queue.droppedSampleCount,
    'last_fix_at': timestamp(status.lastFixAt),
    'last_enqueue_at': timestamp(
      newest(status.queue.lastEnqueueAt, sqliteQueue.lastEnqueueAt),
    ),
    'last_handoff_at': timestamp(status.queue.lastDeliveryAt),
    'last_upload_attempt_at': timestamp(sqliteQueue.lastAttemptAt),
    'delivery_failure_count': failureCount,
    'last_delivery_error_code': boundedDeliveryError(),
    'recovery_pending': status.restorePending,
  };
}
