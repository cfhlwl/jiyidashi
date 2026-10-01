import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'api_client.dart';
import 'motion_sampling_policy.dart';
import 'native_location_bridge.dart';
import 'native_location_controller.dart';
import 'native_motion_sampling_bridge.dart';
import 'offline_queue.dart';
import 'passive_memory_delivery.dart';

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
    required PassiveMemoryDeliveryCoordinator deliveryCoordinator,
    AdaptiveSamplingPolicy policy = const AdaptiveSamplingPolicy(),
    MotionStateMachine? motionStateMachine,
    DateTime Function()? now,
    bool closeNativeBridgeOnDispose = true,
  })  : _api = api,
        _store = store,
        _locationController = locationController,
        _nativeBridge = nativeBridge,
        _deliveryCoordinator = deliveryCoordinator,
        _policy = policy,
        _motionStateMachine = motionStateMachine ?? MotionStateMachine(),
        _now = now ?? DateTime.now,
        _closeNativeBridgeOnDispose = closeNativeBridgeOnDispose,
        _profile = policy.profileFor(motionState: MotionState.unknown);

  final JiYiApiClient _api;
  final OfflineQueueStore _store;
  final NativeLocationController _locationController;
  final NativeMotionSamplingBridge _nativeBridge;
  final PassiveMemoryDeliveryCoordinator _deliveryCoordinator;
  final AdaptiveSamplingPolicy _policy;
  final MotionStateMachine _motionStateMachine;
  final DateTime Function() _now;
  final bool _closeNativeBridgeOnDispose;

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

    final fallbackSamples = <NativeLocationSample>[];
    final report = await _deliveryCoordinator.recoverAndDeliver(
      restoreSessionIfNeeded: false,
      allowProducerResume: false,
      forceDelivery: forceFlush,
      minimumBatchSize: _profile.batchTarget,
      maxBatchAge: _profile.maxBatchAge,
      onNativeSamples: (samples) {
        if (nativeObservation == null) {
          fallbackSamples.addAll(samples);
        }
      },
    );

    // Shared delivery owns all AUTH / Privacy / upload decisions. When it proves auth
    // loss or quarantines native production, refresh the controller's read-only status so
    // foreground UI/motion state cannot keep believing the producer is still running.
    switch (report.status) {
      case PassiveMemoryRecoveryStatus.privacyPaused:
        await _locationController.pauseForPrivacy();
        break;
      case PassiveMemoryRecoveryStatus.authorityChanged:
      case PassiveMemoryRecoveryStatus.serverUnavailable:
      case PassiveMemoryRecoveryStatus.privacyUnavailable:
        await _locationController.privacyStatusUnknown();
        break;
      case PassiveMemoryRecoveryStatus.noSession:
      case PassiveMemoryRecoveryStatus.accountDeletionInProgress:
      case PassiveMemoryRecoveryStatus.nativeUnavailable:
      case PassiveMemoryRecoveryStatus.nativeNotEligible:
        try {
          await _locationController.refresh();
        } catch (_) {
          // The shared delivery boundary has already failed closed. UI status refresh is
          // observability only and cannot reopen producer/upload authority.
        }
        break;
      case PassiveMemoryRecoveryStatus.delivered:
      case PassiveMemoryRecoveryStatus.deferred:
      case PassiveMemoryRecoveryStatus.noWork:
      case PassiveMemoryRecoveryStatus.busy:
      case PassiveMemoryRecoveryStatus.retryableFailure:
      case PassiveMemoryRecoveryStatus.blockedFailure:
        break;
    }

    // [人工注释][S2-004/005] Motion/adaptive policy may consume coordinate-free
    // observation or the exact native samples already authorized/drained by shared delivery.
    // It never drains/ACKs/uploads a second copy of the queue.
    if (nativeObservation != null) {
      _motionStateMachine.observe(
        MotionObservation(
          recordedAt: nativeObservation.recordedAt,
          speedMetersPerSecond: nativeObservation.speedMetersPerSecond,
          accuracyMeters: nativeObservation.accuracyMeters,
        ),
      );
    } else {
      for (final sample in fallbackSamples) {
        _motionStateMachine.observe(
          MotionObservation(
            recordedAt: sample.recordedAt,
            speedMetersPerSecond: sample.speedMetersPerSecond,
            accuracyMeters: sample.accuracyMeters,
          ),
        );
      }
    }

    final refreshedStatus = _locationController.status;
    if (!_locationController.privacyAllowsProduction ||
        refreshedStatus?.runtime != NativeLocationRuntime.running) {
      await _refreshObservability(owner);
      return;
    }

    final recentAccuracy = nativeObservation?.accuracyMeters ??
        (fallbackSamples.isEmpty ? null : fallbackSamples.last.accuracyMeters);
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

    await _refreshObservability(owner);
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
    if (_closeNativeBridgeOnDispose) {
      unawaited(_nativeBridge.close());
    }
    super.dispose();
  }
}
