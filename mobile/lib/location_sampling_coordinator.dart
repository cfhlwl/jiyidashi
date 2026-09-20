import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'api_client.dart';
import 'motion_sampling_policy.dart';
import 'native_location_bridge.dart';
import 'native_location_controller.dart';
import 'native_motion_sampling_bridge.dart';
import 'offline_queue.dart';

class LocationSamplingSnapshot {
  const LocationSamplingSnapshot({
    required this.motionState,
    required this.profile,
    required this.queuedSamples,
    required this.metrics,
  });

  final MotionState motionState;
  final AdaptiveSamplingProfile profile;
  final int queuedSamples;
  final LocationProducerMetrics metrics;
}

class LocationSamplingCoordinator extends ChangeNotifier {
  LocationSamplingCoordinator({
    required JiYiApiClient api,
    required OfflineQueueStore store,
    required NativeLocationController locationController,
    required NativeMotionSamplingBridge nativeBridge,
    AdaptiveSamplingPolicy policy = const AdaptiveSamplingPolicy(),
    MotionStateMachine? motionStateMachine,
    DateTime Function()? now,
  })  : _api = api,
        _store = store,
        _locationController = locationController,
        _nativeBridge = nativeBridge,
        _policy = policy,
        _motionStateMachine = motionStateMachine ?? MotionStateMachine(),
        _now = now ?? DateTime.now,
        _profile = policy.profileFor(motionState: MotionState.unknown);

  final JiYiApiClient _api;
  final OfflineQueueStore _store;
  final NativeLocationController _locationController;
  final NativeMotionSamplingBridge _nativeBridge;
  final AdaptiveSamplingPolicy _policy;
  final MotionStateMachine _motionStateMachine;
  final DateTime Function() _now;

  AdaptiveSamplingProfile _profile;
  LocationProducerMetrics _metrics = const LocationProducerMetrics(
    wakeups: 0,
    samplesAccepted: 0,
    samplesDropped: 0,
    uploadBatches: 0,
    uploadedSamples: 0,
    activeTrackingDuration: Duration.zero,
  );
  int _queuedSamples = 0;
  StreamSubscription<void>? _nativeSubscription;
  Future<void>? _activePump;
  bool _started = false;
  bool _disposed = false;
  bool _quiesced = false;

  MotionState get motionState => _motionStateMachine.state;
  AdaptiveSamplingProfile get profile => _profile;
  LocationSamplingSnapshot get snapshot => LocationSamplingSnapshot(
        motionState: motionState,
        profile: _profile,
        queuedSamples: _queuedSamples,
        metrics: _metrics,
      );

  Future<void> start() async {
    if (_disposed || _started) return;
    _started = true;
    _nativeSubscription = _nativeBridge.samplesAvailable.listen((_) {
      unawaited(pump());
    });
    _locationController.addListener(_locationChanged);
    await pump(forceFlush: true);
  }

  void _locationChanged() {
    if (_disposed || _quiesced) return;
    final status = _locationController.status;
    if (_locationController.privacyAllowsProduction &&
        status?.runtime == NativeLocationRuntime.running) {
      unawaited(pump(forceFlush: true));
    }
  }

  Future<void> pump({bool forceFlush = false}) {
    if (_disposed || _quiesced) return Future<void>.value();
    final active = _activePump;
    if (active != null) {
      return active.then((_) {
        if (_disposed || _quiesced) return Future<void>.value();
        return pump(forceFlush: forceFlush);
      });
    }

    late final Future<void> tracked;
    tracked = _pumpOnce(forceFlush: forceFlush).whenComplete(() {
      if (identical(_activePump, tracked)) {
        _activePump = null;
      }
    });
    _activePump = tracked;
    return tracked;
  }

  Future<void> _pumpOnce({required bool forceFlush}) async {
    final owner = _ownerOrNull();
    final status = _locationController.status;
    if (owner == null ||
        !_locationController.privacyAllowsProduction ||
        status?.runtime != NativeLocationRuntime.running) {
      await _refreshObservability(owner);
      return;
    }

    NativeMotionObservation? nativeObservation;
    try {
      nativeObservation = await _nativeBridge.takeObservation(owner);
    } on MissingPluginException {
      nativeObservation = null;
    } on PlatformException {
      nativeObservation = null;
    }

    final List<NativeLocationSample> nativeSamples;
    try {
      nativeSamples = await _nativeBridge.drainSamples(owner);
    } on MissingPluginException {
      await _refreshObservability(owner);
      return;
    } on PlatformException {
      await _refreshObservability(owner);
      return;
    }
    // [人工注释][S2-004/005] Native quality observation is consumed before raw
    // persistence. A poor coordinate may be rejected natively while its accuracy/speed
    // still reaches the deterministic adaptive policy.
    if (nativeObservation != null) {
      _motionStateMachine.observe(
        MotionObservation(
          recordedAt: nativeObservation.recordedAt,
          speedMetersPerSecond: nativeObservation.speedMetersPerSecond,
          accuracyMeters: nativeObservation.accuracyMeters,
        ),
      );
    } else {
      for (final sample in nativeSamples) {
        _motionStateMachine.observe(
          MotionObservation(
            recordedAt: sample.recordedAt,
            speedMetersPerSecond: sample.speedMetersPerSecond,
            accuracyMeters: sample.accuracyMeters,
          ),
        );
      }
    }

    final ackIds = <String>[];
    for (final sample in nativeSamples) {
      await _store.enqueueLocationSample(
        ownerUserId: owner,
        clientUuid: sample.clientUuid,
        latitude: sample.latitude,
        longitude: sample.longitude,
        accuracyMeters: sample.accuracyMeters,
        speedMetersPerSecond: sample.speedMetersPerSecond,
        recordedAt: sample.recordedAt,
      );
      // Ack only after SQLite commit. If the process dies before this call, the same native
      // UUID is delivered again and enqueueLocationSample returns the existing identical row.
      ackIds.add(sample.clientUuid);
    }
    if (ackIds.isNotEmpty) {
      try {
        await _nativeBridge.acknowledgeSamples(owner, ackIds);
      } on MissingPluginException {
        // SQLite is already durable. Leaving the native copies is safe because the same
        // client_uuid will be idempotently re-enqueued on the next bridge session.
      } on PlatformException {
        // Same fail-closed replay behavior as a process death between SQLite commit and ack.
      }
    }

    final recentAccuracy = nativeObservation?.accuracyMeters ??
        (nativeSamples.isEmpty ? null : nativeSamples.last.accuracyMeters);
    final nextProfile = _policy.profileFor(
      motionState: _motionStateMachine.state,
      recentAccuracyMeters: recentAccuracy,
    );
    if (nextProfile != _profile) {
      _profile = nextProfile;
      try {
        await _nativeBridge.applyProfile(owner, _profile);
      } on MissingPluginException {
        return;
      } on PlatformException {
        return;
      }
    }

    await _maybeFlush(owner, force: forceFlush);
    await _refreshObservability(owner);
  }

  Future<void> _maybeFlush(String owner, {required bool force}) async {
    final queued = await _store.listLocationSamples(owner, limit: 100);
    if (queued.isEmpty) return;

    final oldestAge = _now().toUtc().difference(queued.first.recordedAt);
    if (!force &&
        queued.length < _profile.batchTarget &&
        oldestAge < _profile.maxBatchAge) {
      return;
    }

    if (!await _verifyAuthoritativePrivacy(owner)) return;

    final points = queued
        .map(
          (item) => LocationUploadPoint(
            clientUuid: item.clientUuid,
            latitude: item.latitude,
            longitude: item.longitude,
            accuracyMeters: item.accuracyMeters,
            speedMetersPerSecond: item.speedMetersPerSecond,
            recordedAt: item.recordedAt,
          ),
        )
        .toList(growable: false);
    final ids = queued.map((item) => item.clientUuid).toList(growable: false);

    try {
      final result = await _api.uploadLocationBatch(points);
      if (result.terminalCount != points.length) {
        throw ProtocolException(
          '服务端位置批量响应未覆盖全部提交点',
        );
      }
      await _store.deleteLocationSamples(owner, ids);
      await _nativeBridge.recordUploadBatch(
        owner,
        sampleCount: points.length,
      );
    } on TransportException {
      // Unknown commit is intentionally left in SQLite. The next attempt reuses the exact
      // same client_uuid values and relies on S2-006 durable receipts for deduplication.
    } on ApiException catch (exc) {
      if (exc.statusCode == 409 && exc.message == 'RECORDING_PAUSED') {
        // Privacy may change in the race between the preflight check and POST. Keep the
        // durable UUIDs untouched and converge native production to paused immediately.
        await _locationController.pauseForPrivacy();
        return;
      }
      // [人工注释][S2-005] FUTURE is time-dependent, not a permanent integrity failure.
      // Keep the same durable UUID deliverable so wall-clock convergence can retry it.
      final futureTimestampMayRetry = exc.statusCode == 422 &&
          exc.message == 'LOCATION_RECORDED_AT_IN_FUTURE';
      final retryable = futureTimestampMayRetry ||
          exc.statusCode == 401 ||
          exc.statusCode == 403 ||
          exc.statusCode == 408 ||
          exc.statusCode == 429 ||
          (exc.statusCode >= 500 && exc.statusCode <= 599);
      if (!retryable) {
        await _store.blockLocationSamples(
          owner,
          ids,
          'HTTP ${exc.statusCode}: ${exc.message}',
        );
      }
    } on ProtocolException {
      // A malformed 2xx response is not proof of durable terminal handling. Keep the rows
      // so a later retry can obtain an authoritative aggregate receipt.
    }
  }

  Future<bool> _verifyAuthoritativePrivacy(String owner) async {
    if (_ownerOrNull() != owner ||
        !_locationController.privacyAllowsProduction) {
      return false;
    }
    try {
      final privacy = await _api.getPrivacyStatus();
      if (_ownerOrNull() != owner) return false;
      if (privacy['recording_paused'] == true) {
        await _locationController.pauseForPrivacy();
        return false;
      }
      return true;
    } catch (_) {
      // Sampling upload is fail-closed independently from UI state. A transient privacy
      // lookup failure cannot be treated as permission to upload queued GPS data.
      await _locationController.privacyStatusUnknown();
      return false;
    }
  }

  String? _ownerOrNull() {
    final owner = _api.authenticatedUserId?.trim();
    if (owner == null ||
        owner.isEmpty ||
        owner != _locationController.ownerUserId) {
      return null;
    }
    return owner;
  }

  Future<void> _refreshObservability(String? owner) async {
    if (owner == null || _disposed) return;
    try {
      final results = await Future.wait<Object>([
        _nativeBridge.metrics(owner),
        _store.countLocationSamples(owner),
      ]);
      if (_disposed) return;
      _metrics = results[0] as LocationProducerMetrics;
      _queuedSamples = results[1] as int;
      notifyListeners();
    } catch (_) {
      // Metrics are diagnostics only. Failure to read them must never change privacy,
      // permission, queue durability, or producer state.
    }
  }

  Future<void> suspendForLogout() async {
    _quiesced = true;
    await _nativeSubscription?.cancel();
    _nativeSubscription = null;
    final active = _activePump;
    if (active != null) {
      try {
        await active;
      } catch (_) {}
    }
  }

  Future<void> quiesceForAccountDeletion() async {
    _quiesced = true;
    await _nativeSubscription?.cancel();
    _nativeSubscription = null;
    final active = _activePump;
    if (active != null) {
      try {
        await active;
      } catch (_) {}
    }
    final owner = _locationController.ownerUserId;
    try {
      await _nativeBridge.purgeOwner(owner);
    } on MissingPluginException {
      // Native cleanup is unavailable, but account deletion must still remove the
      // durable SQLite raw-location payload for this owner.
    } on PlatformException {
      // Same rule: local owner purge cannot be blocked by optional bridge cleanup.
    }
    await _store.purgeLocationSamples(owner);
  }

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _locationController.removeListener(_locationChanged);
    unawaited(_nativeSubscription?.cancel());
    unawaited(_nativeBridge.close());
    super.dispose();
  }
}
