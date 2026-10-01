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
      final aggregates = _stringMap(raw['aggregates']);
      if (health == null ||
          today == null ||
          aggregates == null ||
          !_containsKeys(raw, _topLevelRequiredKeys) ||
          !_containsKeys(health, _healthRequiredKeys) ||
          !_containsKeys(today, _todayRequiredKeys) ||
          !_containsKeys(aggregates, _aggregateRequiredKeys)) {
        return const RecordingHealthView.unknown();
      }

      final status = _parseHealthStatusStrict(health['status']);
      final coverage = _parseCoverageStateStrict(today['coverage_state']);
      final reason = _requiredEnum(health['status_reason'], _healthReasons);
      final localDay = _requiredLocalDay(today['local_day']);
      final timezone = _requiredNonEmptyString(today['timezone']);
      final serverObservedAt = _requiredTimestamp(raw['server_observed_at']);
      final updatedAt = _requiredTimestamp(health['updated_at']);
      final nativeStateObserved = raw['native_state_observed'];
      if (status == null ||
          coverage == null ||
          reason == null ||
          localDay == null ||
          timezone == null ||
          serverObservedAt == null ||
          updatedAt == null ||
          nativeStateObserved is! bool) {
        return const RecordingHealthView.unknown();
      }

      if (!_isNullableBool(health['automatic_enabled']) ||
          health['privacy_paused'] is! bool ||
          !_isNullableEnum(health['permission_state'], _permissionStates) ||
          !_isNullableEnum(
            health['location_services_state'],
            _locationServiceStates,
          ) ||
          !_isNullableEnum(
            health['background_runtime_state'],
            _backgroundRuntimeStates,
          ) ||
          !_isNullableEnum(
            health['battery_optimization_state'],
            _batteryOptimizationStates,
          ) ||
          !_isNullableEnum(
            health['native_producer_state'],
            _producerStates,
          ) ||
          !_isNullableEnum(
            health['last_delivery_error_code'],
            _deliveryErrorCodes,
          ) ||
          _requiredEnum(
                health['recording_gap_state'],
                _recordingGapStates,
              ) ==
              null ||
          !_allNullableTimestampsValid(health, _healthTimestampKeys) ||
          health['capacity_pressure'] is! bool ||
          health['recovery_pending'] is! bool) {
        return const RecordingHealthView.unknown();
      }

      final nativeQueueDepth = _requiredNonNegativeInt(
        health['native_queue_depth'],
      );
      final nativeQueueCapacity = _requiredNonNegativeInt(
        health['native_queue_capacity'],
      );
      final sqliteQueueDepth = _requiredNonNegativeInt(
        health['sqlite_queue_depth'],
      );
      final deliveryFailureCount = _requiredNonNegativeInt(
        health['delivery_failure_count'],
      );
      final coveredDurationSeconds = _requiredNonNegativeInt(
        today['covered_duration_seconds'],
      );
      final knownGapDurationSeconds = _requiredNonNegativeInt(
        today['known_gap_duration_seconds'],
      );
      final largestKnownGapSeconds = _requiredNonNegativeInt(
        today['largest_known_gap_seconds'],
      );
      final trustedLocationSampleCount = _requiredNonNegativeInt(
        today['trusted_location_sample_count'],
      );
      final visitCount = _requiredNonNegativeInt(today['visit_count']);
      final memoryCount = _requiredNonNegativeInt(today['memory_count']);
      if (nativeQueueDepth == null ||
          nativeQueueCapacity == null ||
          sqliteQueueDepth == null ||
          deliveryFailureCount == null ||
          coveredDurationSeconds == null ||
          knownGapDurationSeconds == null ||
          largestKnownGapSeconds == null ||
          trustedLocationSampleCount == null ||
          visitCount == null ||
          memoryCount == null ||
          largestKnownGapSeconds > knownGapDurationSeconds ||
          today['has_capacity_pressure'] is! bool ||
          today['has_recorded_gap'] is! bool ||
          today['has_unexplained_gap'] is! bool ||
          !_allNullableTimestampsValid(
            today,
            const <String>['first_observed_at', 'last_observed_at'],
          ) ||
          !_validGapList(today['recent_gaps']) ||
          !_validGapList(raw['recent_gaps']) ||
          !_validGapReasonList(raw['active_gap_reasons']) ||
          !_validAggregates(aggregates)) {
        return const RecordingHealthView.unknown();
      }

      final firstObservedAt = _date(today['first_observed_at']);
      final lastObservedAt = _date(today['last_observed_at']);
      if (firstObservedAt != null &&
          lastObservedAt != null &&
          firstObservedAt.isAfter(lastObservedAt)) {
        return const RecordingHealthView.unknown();
      }
      if (today['has_unexplained_gap'] == true &&
          today['has_recorded_gap'] != true) {
        return const RecordingHealthView.unknown();
      }

      final lastFixAt = _date(health['last_fix_at']);
      final lastServerAckAt = _date(health['last_server_ack_at']);
      final timestampUpperBound =
          serverObservedAt.add(const Duration(minutes: 2));
      for (final key in _healthTimestampKeys) {
        final value = _date(health[key]);
        if (value != null && value.isAfter(timestampUpperBound)) {
          return const RecordingHealthView.unknown();
        }
      }
      if (firstObservedAt != null && firstObservedAt.isAfter(timestampUpperBound) ||
          lastObservedAt != null && lastObservedAt.isAfter(timestampUpperBound) ||
          updatedAt.isAfter(timestampUpperBound)) {
        return const RecordingHealthView.unknown();
      }

      final privacyPaused = health['privacy_paused'] as bool;
      final automaticEnabled = health['automatic_enabled'] as bool?;
      final permissionState = health['permission_state'] as String?;
      final locationServicesState =
          health['location_services_state'] as String?;
      final backgroundRuntimeState =
          health['background_runtime_state'] as String?;
      final nativeProducerState = health['native_producer_state'] as String?;
      final capacityPressure = health['capacity_pressure'] as bool;
      final recoveryPending = health['recovery_pending'] as bool;
      final recordingGapState = health['recording_gap_state'] as String;

      if (status == RecordingHealthStatus.healthy &&
          (reason != 'RECENT_CAPTURE_AND_ACK' ||
              !nativeStateObserved ||
              automaticEnabled != true ||
              privacyPaused ||
              permissionState != 'BACKGROUND' ||
              locationServicesState != 'ON' ||
              backgroundRuntimeState != 'ELIGIBLE' ||
              nativeProducerState != 'RUNNING' ||
              capacityPressure ||
              recoveryPending ||
              recordingGapState != 'NONE' ||
              lastFixAt == null ||
              lastServerAckAt == null)) {
        return const RecordingHealthView.unknown();
      }
      if (status == RecordingHealthStatus.paused &&
          (!privacyPaused || reason != 'PRIVACY_PAUSED')) {
        return const RecordingHealthView.unknown();
      }

      final gaps = _gapReasons(raw['recent_gaps']);
      final activeGaps = (raw['active_gap_reasons'] as List)
          .cast<String>()
          .take(8)
          .toList(growable: false);

      return RecordingHealthView(
        status: status,
        reason: reason,
        privacyPaused: privacyPaused,
        nativeStateObserved: nativeStateObserved,
        automaticEnabled: automaticEnabled,
        permissionState: permissionState,
        locationServicesState: locationServicesState,
        backgroundRuntimeState: backgroundRuntimeState,
        coverageState: coverage,
        localDay: localDay,
        timezone: timezone,
        coveredDurationSeconds: coveredDurationSeconds,
        knownGapDurationSeconds: knownGapDurationSeconds,
        hasRecordedGap: today['has_recorded_gap'] as bool,
        hasUnexplainedGap: today['has_unexplained_gap'] as bool,
        nativeQueueDepth: nativeQueueDepth,
        sqliteQueueDepth: sqliteQueueDepth,
        capacityPressure: capacityPressure,
        deliveryFailureCount: deliveryFailureCount,
        recoveryPending: recoveryPending,
        lastFixAt: lastFixAt,
        lastServerAckAt: lastServerAckAt,
        recentGapReasons: gaps,
        activeGapReasons: activeGaps,
        malformed: false,
      );
    } catch (_) {
      return const RecordingHealthView.unknown();
    }
  }

  static const Set<String> _healthReasons = <String>{
    'RECENT_CAPTURE_AND_ACK',
    'PRIVACY_PAUSED',
    'PERMISSION_BLOCKED',
    'LOCATION_SERVICES_OFF',
    'AUTOMATIC_DISABLED',
    'PLATFORM_RESTRICTED',
    'QUEUE_BACKLOG',
    'QUEUE_CAPACITY_PRESSURE',
    'DELIVERY_BACKLOG',
    'DELIVERY_FAILURE',
    'RECOVERY_PENDING',
    'PRODUCER_NOT_RUNNING',
    'NO_RECENT_FIX',
    'NO_RECENT_ACK',
    'RECORDED_GAP',
    'NATIVE_STATE_UNAVAILABLE',
    'CLIENT_STATE_STALE',
  };
  static const Set<String> _permissionStates = <String>{
    'BACKGROUND',
    'FOREGROUND',
    'DENIED',
    'RESTRICTED',
    'NOT_DETERMINED',
    'UNKNOWN',
  };
  static const Set<String> _locationServiceStates = <String>{
    'ON',
    'OFF',
    'UNKNOWN',
  };
  static const Set<String> _backgroundRuntimeStates = <String>{
    'ELIGIBLE',
    'RESTRICTED',
    'UNKNOWN',
  };
  static const Set<String> _batteryOptimizationStates = <String>{
    'EXEMPT',
    'OPTIMIZED',
    'NOT_APPLICABLE',
    'UNKNOWN',
  };
  static const Set<String> _producerStates = <String>{
    'RUNNING',
    'PAUSED',
    'STOPPED',
    'UNKNOWN',
  };
  static const Set<String> _deliveryErrorCodes = <String>{
    'NETWORK_UNAVAILABLE',
    'SERVER_RETRYABLE',
    'AUTHORITY_REJECTED',
    'PRIVACY_REJECTED',
    'PROTOCOL_ERROR',
    'QUEUE_ERROR',
    'UNKNOWN',
  };
  static const Set<String> _gapReasonsAllowed = <String>{
    'PERMISSION_BLOCKED',
    'LOCATION_SERVICES_OFF',
    'PRIVACY_PAUSED',
    'PLATFORM_RESTRICTED',
    'QUEUE_CAPACITY_PRESSURE',
    'DELIVERY_BACKLOG',
    'PRODUCER_NOT_RUNNING',
    'NO_RECENT_FIX',
    'UNKNOWN',
  };
  static const Set<String> _recordingGapStates = <String>{
    'NONE',
    'KNOWN',
    'UNKNOWN',
  };

  static const List<String> _topLevelRequiredKeys = <String>[
    'health',
    'today',
    'aggregates',
    'recent_gaps',
    'active_gap_reasons',
    'server_observed_at',
    'native_state_observed',
  ];
  static const List<String> _healthRequiredKeys = <String>[
    'status',
    'status_reason',
    'automatic_enabled',
    'privacy_paused',
    'permission_state',
    'location_services_state',
    'background_runtime_state',
    'battery_optimization_state',
    'native_producer_state',
    'native_queue_depth',
    'native_queue_capacity',
    'native_oldest_pending_at',
    'sqlite_queue_depth',
    'capacity_pressure',
    'last_fix_at',
    'last_enqueue_at',
    'last_handoff_at',
    'last_upload_attempt_at',
    'last_upload_success_at',
    'last_server_ack_at',
    'last_visit_at',
    'delivery_failure_count',
    'last_delivery_error_code',
    'recovery_pending',
    'recording_gap_state',
    'updated_at',
  ];
  static const List<String> _healthTimestampKeys = <String>[
    'native_oldest_pending_at',
    'last_fix_at',
    'last_enqueue_at',
    'last_handoff_at',
    'last_upload_attempt_at',
    'last_upload_success_at',
    'last_server_ack_at',
    'last_visit_at',
  ];
  static const List<String> _todayRequiredKeys = <String>[
    'local_day',
    'timezone',
    'first_observed_at',
    'last_observed_at',
    'trusted_location_sample_count',
    'visit_count',
    'memory_count',
    'covered_duration_seconds',
    'known_gap_duration_seconds',
    'largest_known_gap_seconds',
    'coverage_state',
    'has_capacity_pressure',
    'has_recorded_gap',
    'has_unexplained_gap',
    'recent_gaps',
  ];
  static const List<String> _aggregateRequiredKeys = <String>[
    'healthy_days_7d',
    'healthy_days_30d',
    'evidence_days_7d',
    'evidence_days_30d',
    'gap_hours_7d',
    'gap_hours_30d',
    'bounded_gap_hours_7d',
    'bounded_gap_hours_30d',
    'days_with_capacity_pressure',
    'days_with_permission_block',
    'current_capacity_pressure',
    'current_permission_block',
  ];

  static bool _containsKeys(Map<String, dynamic> value, List<String> keys) {
    return keys.every(value.containsKey);
  }

  static Map<String, dynamic>? _stringMap(Object? value) {
    if (value is! Map) return null;
    return value.map<String, dynamic>(
      (key, item) => MapEntry(key.toString(), item),
    );
  }

  static String? _requiredEnum(Object? value, Set<String> allowed) {
    return value is String && allowed.contains(value) ? value : null;
  }

  static String? _requiredNonEmptyString(Object? value) {
    if (value is! String || value.trim().isEmpty) return null;
    return value;
  }

  static String? _requiredLocalDay(Object? value) {
    if (value is! String ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) {
      return null;
    }
    final parsed = DateTime.tryParse(value);
    if (parsed == null ||
        parsed.year.toString().padLeft(4, '0') != value.substring(0, 4) ||
        parsed.month.toString().padLeft(2, '0') != value.substring(5, 7) ||
        parsed.day.toString().padLeft(2, '0') != value.substring(8, 10)) {
      return null;
    }
    return value;
  }

  static int? _requiredNonNegativeInt(Object? value, {int? max}) {
    if (value is! int || value < 0 || (max != null && value > max)) {
      return null;
    }
    return value;
  }

  static bool _isNullableBool(Object? value) {
    return value == null || value is bool;
  }

  static bool _isNullableEnum(Object? value, Set<String> allowed) {
    return value == null || (value is String && allowed.contains(value));
  }

  static DateTime? _requiredTimestamp(Object? value) {
    if (value is! String) return null;
    final parsed = DateTime.tryParse(value);
    if (parsed == null || !parsed.isUtc) return null;
    return parsed.toUtc();
  }

  static bool _isNullableTimestamp(Object? value) {
    return value == null || _requiredTimestamp(value) != null;
  }

  static bool _allNullableTimestampsValid(
    Map<String, dynamic> value,
    List<String> keys,
  ) {
    return keys.every((key) => _isNullableTimestamp(value[key]));
  }

  static DateTime? _date(Object? value) {
    if (value == null) return null;
    return _requiredTimestamp(value);
  }

  static bool _validGapList(Object? value) {
    if (value is! List || value.length > 8) return false;
    for (final item in value) {
      final gap = _stringMap(item);
      if (gap == null ||
          !_containsKeys(
            gap,
            const <String>[
              'reason',
              'started_at',
              'ended_at',
              'duration_seconds',
            ],
          ) ||
          _requiredEnum(gap['reason'], _gapReasonsAllowed) == null) {
        return false;
      }
      final startedAt = _requiredTimestamp(gap['started_at']);
      final endedAt = _requiredTimestamp(gap['ended_at']);
      final duration = _requiredNonNegativeInt(gap['duration_seconds']);
      if (startedAt == null ||
          endedAt == null ||
          duration == null ||
          endedAt.isBefore(startedAt)) {
        return false;
      }
    }
    return true;
  }

  static List<String> _gapReasons(Object? value) {
    return (value as List)
        .map(_stringMap)
        .whereType<Map<String, dynamic>>()
        .map((gap) => gap['reason'] as String)
        .take(8)
        .toList(growable: false);
  }

  static bool _validGapReasonList(Object? value) {
    if (value is! List || value.length > 8) return false;
    return value.every(
      (item) => item is String && _gapReasonsAllowed.contains(item),
    );
  }

  static bool _validAggregates(Map<String, dynamic> value) {
    final healthy7 = _requiredNonNegativeInt(value['healthy_days_7d'], max: 7);
    final healthy30 =
        _requiredNonNegativeInt(value['healthy_days_30d'], max: 30);
    final evidence7 =
        _requiredNonNegativeInt(value['evidence_days_7d'], max: 7);
    final evidence30 =
        _requiredNonNegativeInt(value['evidence_days_30d'], max: 30);
    if (healthy7 == null ||
        healthy30 == null ||
        evidence7 == null ||
        evidence30 == null ||
        healthy7 > evidence7 ||
        healthy30 > evidence30 ||
        !_isNullableNonNegativeNum(value['gap_hours_7d']) ||
        !_isNullableNonNegativeNum(value['gap_hours_30d']) ||
        !_isNonNegativeNum(value['bounded_gap_hours_7d']) ||
        !_isNonNegativeNum(value['bounded_gap_hours_30d']) ||
        !_isNullableBoundedInt(
          value['days_with_capacity_pressure'],
          30,
        ) ||
        !_isNullableBoundedInt(
          value['days_with_permission_block'],
          30,
        ) ||
        !_isNullableBool(value['current_capacity_pressure']) ||
        !_isNullableBool(value['current_permission_block'])) {
      return false;
    }
    return true;
  }

  static bool _isNonNegativeNum(Object? value) {
    return value is num && value.isFinite && value >= 0;
  }

  static bool _isNullableNonNegativeNum(Object? value) {
    return value == null || _isNonNegativeNum(value);
  }

  static bool _isNullableBoundedInt(Object? value, int max) {
    return value == null ||
        (value is int && value >= 0 && value <= max);
  }

  static RecordingHealthStatus? _parseHealthStatusStrict(Object? value) {
    return switch (value) {
      'HEALTHY' => RecordingHealthStatus.healthy,
      'DEGRADED' => RecordingHealthStatus.degraded,
      'PAUSED' => RecordingHealthStatus.paused,
      'BLOCKED' => RecordingHealthStatus.blocked,
      'RECOVERING' => RecordingHealthStatus.recovering,
      'UNKNOWN' => RecordingHealthStatus.unknown,
      _ => null,
    };
  }

  static RecordingCoverageState? _parseCoverageStateStrict(Object? value) {
    return switch (value) {
      'HEALTHY' => RecordingCoverageState.healthy,
      'PARTIAL' => RecordingCoverageState.partial,
      'GAPPED' => RecordingCoverageState.gapped,
      'UNKNOWN' => RecordingCoverageState.unknown,
      _ => null,
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
