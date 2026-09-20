import 'dart:async';

import 'package:flutter/services.dart';

import 'motion_sampling_policy.dart';

class NativeLocationSample {
  const NativeLocationSample({
    required this.clientUuid,
    required this.latitude,
    required this.longitude,
    required this.recordedAt,
    this.accuracyMeters,
    this.speedMetersPerSecond,
  });

  final String clientUuid;
  final double latitude;
  final double longitude;
  final DateTime recordedAt;
  final double? accuracyMeters;
  final double? speedMetersPerSecond;

  factory NativeLocationSample.fromPlatform(Object? value) {
    if (value is! Map) {
      throw const FormatException('native location sample must be a map');
    }
    final map = <String, Object?>{};
    value.forEach((key, item) => map[key.toString()] = item);
    final clientUuid = map['client_uuid']?.toString().trim() ?? '';
    final latitude = _double(map['latitude']);
    final longitude = _double(map['longitude']);
    final recordedAt = DateTime.tryParse(map['recorded_at']?.toString() ?? '');
    if (clientUuid.isEmpty ||
        latitude == null ||
        longitude == null ||
        recordedAt == null ||
        latitude < -90 ||
        latitude > 90 ||
        longitude < -180 ||
        longitude > 180) {
      throw const FormatException('native location sample is invalid');
    }
    return NativeLocationSample(
      clientUuid: clientUuid,
      latitude: latitude,
      longitude: longitude,
      recordedAt: recordedAt.toUtc(),
      accuracyMeters: _double(map['accuracy']),
      speedMetersPerSecond: _double(map['speed']),
    );
  }

  static double? _double(Object? value) {
    if (value is num) return value.toDouble();
    return double.tryParse(value?.toString() ?? '');
  }
}

class NativeMotionObservation {
  const NativeMotionObservation({
    required this.recordedAt,
    this.accuracyMeters,
    this.speedMetersPerSecond,
  });

  final DateTime recordedAt;
  final double? accuracyMeters;
  final double? speedMetersPerSecond;

  factory NativeMotionObservation.fromPlatform(Object? value) {
    if (value is! Map) {
      throw const FormatException('native motion observation must be a map');
    }
    final rawMillis = value['recorded_at_millis'];
    final millis = rawMillis is num
        ? rawMillis.toInt()
        : int.tryParse(rawMillis?.toString() ?? '');
    if (millis == null || millis <= 0) {
      throw const FormatException('native motion observation timestamp is invalid');
    }
    return NativeMotionObservation(
      recordedAt: DateTime.fromMillisecondsSinceEpoch(millis, isUtc: true),
      accuracyMeters: NativeLocationSample._double(value['accuracy']),
      speedMetersPerSecond: NativeLocationSample._double(value['speed']),
    );
  }
}

class LocationProducerMetrics {
  const LocationProducerMetrics({
    required this.wakeups,
    required this.samplesAccepted,
    required this.samplesDropped,
    required this.uploadBatches,
    required this.uploadedSamples,
    required this.activeTrackingDuration,
  });

  final int wakeups;
  final int samplesAccepted;
  final int samplesDropped;
  final int uploadBatches;
  final int uploadedSamples;
  final Duration activeTrackingDuration;

  factory LocationProducerMetrics.fromPlatform(Object? value) {
    if (value is! Map) {
      return const LocationProducerMetrics(
        wakeups: 0,
        samplesAccepted: 0,
        samplesDropped: 0,
        uploadBatches: 0,
        uploadedSamples: 0,
        activeTrackingDuration: Duration.zero,
      );
    }
    int integer(String key) {
      final raw = value[key];
      if (raw is int) return raw;
      if (raw is num) return raw.toInt();
      return int.tryParse(raw?.toString() ?? '') ?? 0;
    }

    return LocationProducerMetrics(
      wakeups: integer('wakeups'),
      samplesAccepted: integer('samples_accepted'),
      samplesDropped: integer('samples_dropped'),
      uploadBatches: integer('upload_batches'),
      uploadedSamples: integer('uploaded_samples'),
      activeTrackingDuration: Duration(
        milliseconds: integer('active_tracking_ms'),
      ),
    );
  }
}

abstract interface class NativeMotionSamplingBridge {
  Stream<void> get samplesAvailable;

  Future<List<NativeLocationSample>> drainSamples(
    String ownerUserId, {
    int limit = 100,
  });

  Future<NativeMotionObservation?> takeObservation(String ownerUserId);

  Future<void> acknowledgeSamples(
    String ownerUserId,
    List<String> clientUuids,
  );

  Future<void> applyProfile(
    String ownerUserId,
    AdaptiveSamplingProfile profile,
  );

  Future<LocationProducerMetrics> metrics(String ownerUserId);

  Future<void> recordUploadBatch(
    String ownerUserId, {
    required int sampleCount,
  });

  Future<void> purgeOwner(String ownerUserId);

  Future<void> close();
}

/// Sampling uses the existing native-location MethodChannel so no second permission/lifecycle
/// authority is introduced. Native code may only notify that durable samples exist; Flutter
/// still decides whether privacy is active before draining or uploading them.
class MethodChannelNativeMotionSamplingBridge
    implements NativeMotionSamplingBridge {
  MethodChannelNativeMotionSamplingBridge({
    MethodChannel channel = const MethodChannel('cn.jiyidashi/native_location'),
  }) : _channel = channel {
    _channel.setMethodCallHandler(_onNativeMethod);
  }

  final MethodChannel _channel;
  final StreamController<void> _sampleEvents =
      StreamController<void>.broadcast();
  bool _closed = false;

  Map<String, Object?> _ownerArgs(String ownerUserId) {
    final owner = ownerUserId.trim();
    if (owner.isEmpty) {
      throw ArgumentError.value(
        ownerUserId,
        'ownerUserId',
        'authenticated user id is required',
      );
    }
    return <String, Object?>{'owner_user_id': owner};
  }

  Future<void> _onNativeMethod(MethodCall call) async {
    if (_closed) return;
    if (call.method == 'samplesAvailable') {
      _sampleEvents.add(null);
    }
  }

  @override
  Stream<void> get samplesAvailable => _sampleEvents.stream;

  @override
  Future<List<NativeLocationSample>> drainSamples(
    String ownerUserId, {
    int limit = 100,
  }) async {
    final args = _ownerArgs(ownerUserId)..['limit'] = limit.clamp(1, 500);
    final raw = await _channel.invokeMethod<List<Object?>>(
      'drainLocationSamples',
      args,
    );
    return (raw ?? const <Object?>[])
        .map(NativeLocationSample.fromPlatform)
        .toList(growable: false);
  }

  @override
  Future<NativeMotionObservation?> takeObservation(String ownerUserId) async {
    final raw = await _channel.invokeMethod<Object?>(
      'takeMotionObservation',
      _ownerArgs(ownerUserId),
    );
    if (raw == null) return null;
    // [人工注释][S2-004/005] Observation has quality/motion metadata only; coordinates
    // remain exclusively in the separately gated durable raw sample queue.
    return NativeMotionObservation.fromPlatform(raw);
  }

  @override
  Future<void> acknowledgeSamples(
    String ownerUserId,
    List<String> clientUuids,
  ) async {
    if (clientUuids.isEmpty) return;
    final args = _ownerArgs(ownerUserId)
      ..['client_uuids'] = clientUuids;
    await _channel.invokeMethod<void>('ackLocationSamples', args);
  }

  @override
  Future<void> applyProfile(
    String ownerUserId,
    AdaptiveSamplingProfile profile,
  ) async {
    final args = _ownerArgs(ownerUserId)
      ..addAll(<String, Object?>{
        'motion_state': profile.motionState.name,
        'min_interval_ms': profile.minInterval.inMilliseconds,
        'min_distance_m': profile.minDistanceMeters,
        'max_accuracy_m': profile.maxAcceptedAccuracyMeters,
      });
    await _channel.invokeMethod<void>('applySamplingProfile', args);
  }

  @override
  Future<LocationProducerMetrics> metrics(String ownerUserId) async {
    final raw = await _channel.invokeMethod<Object?>(
      'locationMetrics',
      _ownerArgs(ownerUserId),
    );
    return LocationProducerMetrics.fromPlatform(raw);
  }

  @override
  Future<void> recordUploadBatch(
    String ownerUserId, {
    required int sampleCount,
  }) async {
    if (sampleCount <= 0) return;
    final args = _ownerArgs(ownerUserId)..['sample_count'] = sampleCount;
    await _channel.invokeMethod<void>('recordLocationUploadBatch', args);
  }

  @override
  Future<void> purgeOwner(String ownerUserId) async {
    await _channel.invokeMethod<void>(
      'purgeLocationSamplingOwner',
      _ownerArgs(ownerUserId),
    );
  }

  @override
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _channel.setMethodCallHandler(null);
    await _sampleEvents.close();
  }
}
