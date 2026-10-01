import 'dart:async';

import 'package:flutter/services.dart';

import 'api_client.dart';
import 'native_location_bridge.dart';
import 'native_motion_sampling_bridge.dart';
import 'offline_queue.dart';

enum PassiveMemoryRecoveryStatus {
  delivered,
  deferred,
  noWork,
  busy,
  noSession,
  accountDeletionInProgress,
  serverUnavailable,
  authorityChanged,
  privacyPaused,
  privacyUnavailable,
  nativeUnavailable,
  nativeNotEligible,
  retryableFailure,
  blockedFailure,
}

class PassiveMemoryRecoveryReport {
  const PassiveMemoryRecoveryReport({
    required this.status,
    this.ownerUserId,
    this.nativeHandedOff = 0,
    this.deliveryAttempted = 0,
    this.deliveryCompleted = 0,
    this.sessionRestored = false,
  });

  final PassiveMemoryRecoveryStatus status;
  final String? ownerUserId;
  final int nativeHandedOff;
  final int deliveryAttempted;
  final int deliveryCompleted;
  final bool sessionRestored;
}

/// UI-independent CORE-001 authority/delivery boundary.
///
/// This coordinator is safe to call from the normal Flutter shell and from a platform
/// recovery entry point. It never treats native enabled/runtime state as account authority:
/// a durable AUTH-001 session is refreshed first, then server Privacy is read fresh, and
/// only then may native samples be handed off or uploaded.
class PassiveMemoryDeliveryCoordinator {
  PassiveMemoryDeliveryCoordinator({
    required JiYiApiClient api,
    required OfflineQueueStore store,
    required NativeLocationBridge locationBridge,
    required NativeMotionSamplingBridge samplingBridge,
  })  : _api = api,
        _store = store,
        _locationBridge = locationBridge,
        _samplingBridge = samplingBridge;

  final JiYiApiClient _api;
  final OfflineQueueStore _store;
  final NativeLocationBridge _locationBridge;
  final NativeMotionSamplingBridge _samplingBridge;

  Future<PassiveMemoryRecoveryReport>? _activeRecovery;

  Future<PassiveMemoryRecoveryReport> recoverAndDeliver({
    bool restoreSessionIfNeeded = false,
    bool allowProducerResume = true,
    bool forceDelivery = true,
    int minimumBatchSize = 1,
    Duration maxBatchAge = Duration.zero,
    void Function(List<NativeLocationSample>)? onNativeSamples,
  }) {
    final active = _activeRecovery;
    if (active != null) return active;

    late final Future<PassiveMemoryRecoveryReport> tracked;
    tracked = _recoverAndDeliverOnce(
      restoreSessionIfNeeded: restoreSessionIfNeeded,
      allowProducerResume: allowProducerResume,
      forceDelivery: forceDelivery,
      minimumBatchSize: minimumBatchSize,
      maxBatchAge: maxBatchAge,
      onNativeSamples: onNativeSamples,
    ).whenComplete(() {
      if (identical(_activeRecovery, tracked)) {
        _activeRecovery = null;
      }
    });
    _activeRecovery = tracked;
    return tracked;
  }

  Future<PassiveMemoryRecoveryReport> _recoverAndDeliverOnce({
    required bool restoreSessionIfNeeded,
    required bool allowProducerResume,
    required bool forceDelivery,
    required int minimumBatchSize,
    required Duration maxBatchAge,
    required void Function(List<NativeLocationSample>)? onNativeSamples,
  }) async {
    if (minimumBatchSize <= 0) {
      throw ArgumentError.value(
        minimumBatchSize,
        'minimumBatchSize',
        'must be positive',
      );
    }
    if (maxBatchAge.isNegative) {
      throw ArgumentError.value(
        maxBatchAge,
        'maxBatchAge',
        'must not be negative',
      );
    }
    var restored = false;
    if (_api.authenticatedUserId == null && restoreSessionIfNeeded) {
      final result = await _api.restorePersistedSession();
      switch (result) {
        case AuthRestoreStatus.restored:
          restored = true;
          break;
        case AuthRestoreStatus.noPersistedSession:
        case AuthRestoreStatus.invalidSession:
          return const PassiveMemoryRecoveryReport(
            status: PassiveMemoryRecoveryStatus.noSession,
          );
        case AuthRestoreStatus.serverUnavailable:
          return const PassiveMemoryRecoveryReport(
            status: PassiveMemoryRecoveryStatus.serverUnavailable,
          );
      }
    }

    final preflightOwner = _api.authenticatedUserId?.trim();
    if (preflightOwner == null || preflightOwner.isEmpty) {
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.noSession,
      );
    }

    try {
      // A currently published owner still has to prove the server-side durable session
      // before a background/recovery path is allowed to use it.
      await _api.revalidateAuthenticatedOwnerAuthority();
    } on TransportException {
      await _pauseNativeFailClosed(preflightOwner);
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.serverUnavailable,
      );
    } on ApiException catch (error) {
      if (error.statusCode == 400 || error.statusCode == 401) {
        await _disableNativeFailClosed(preflightOwner);
        return const PassiveMemoryRecoveryReport(
          status: PassiveMemoryRecoveryStatus.noSession,
        );
      }
      await _pauseNativeFailClosed(preflightOwner);
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.serverUnavailable,
      );
    } on ProtocolException {
      await _pauseNativeFailClosed(preflightOwner);
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.authorityChanged,
      );
    }

    try {
      // AUTH refresh proves the session, but account deletion is a separate owner
      // publication authority. Reuse the same profile guard as normal cold-start recovery.
      await _api.getProfile();
    } on TransportException {
      await _pauseNativeFailClosed(preflightOwner);
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.serverUnavailable,
      );
    } on ApiException catch (error) {
      if (error.statusCode == 423 &&
          error.message == 'ACCOUNT_DELETION_IN_PROGRESS') {
        await _disableNativeFailClosed(preflightOwner);
        return const PassiveMemoryRecoveryReport(
          status: PassiveMemoryRecoveryStatus.accountDeletionInProgress,
        );
      }
      if (error.statusCode == 400 || error.statusCode == 401) {
        await _disableNativeFailClosed(preflightOwner);
        return const PassiveMemoryRecoveryReport(
          status: PassiveMemoryRecoveryStatus.noSession,
        );
      }
      await _pauseNativeFailClosed(preflightOwner);
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.serverUnavailable,
      );
    } on ProtocolException {
      await _pauseNativeFailClosed(preflightOwner);
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.authorityChanged,
      );
    }

    final owner = _api.authenticatedUserId?.trim();
    if (owner == null || owner.isEmpty) {
      return const PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.noSession,
      );
    }
    final generation = _api.sessionVersion;
    final sessionId = _api.authenticatedSessionId;
    if (sessionId == null ||
        !await _authorityStillPersisted(owner, generation, sessionId)) {
      return await _stale(owner, restored);
    }

    NativeLocationStatus nativeStatus;
    try {
      nativeStatus = await _locationBridge.status(owner);
    } on MissingPluginException {
      return PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.nativeUnavailable,
        ownerUserId: owner,
        sessionRestored: restored,
      );
    } on PlatformException {
      return PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.nativeUnavailable,
        ownerUserId: owner,
        sessionRestored: restored,
      );
    }
    if (!await _authorityStillPersisted(owner, generation, sessionId)) {
      return await _stale(owner, restored);
    }
    if (!nativeStatus.supported) {
      return PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.nativeUnavailable,
        ownerUserId: owner,
        sessionRestored: restored,
      );
    }

    Map<String, dynamic> privacy;
    try {
      privacy = await _api.getPrivacyStatus();
    } on TransportException {
      await _pauseNativeFailClosed(owner);
      return PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.privacyUnavailable,
        ownerUserId: owner,
        sessionRestored: restored,
      );
    } on ApiException catch (error) {
      if (error.statusCode == 400 || error.statusCode == 401) {
        await _disableNativeFailClosed(owner);
        return PassiveMemoryRecoveryReport(
          status: PassiveMemoryRecoveryStatus.noSession,
          ownerUserId: owner,
          sessionRestored: restored,
        );
      }
      await _pauseNativeFailClosed(owner);
      return PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.privacyUnavailable,
        ownerUserId: owner,
        sessionRestored: restored,
      );
    }
    if (!await _authorityStillPersisted(owner, generation, sessionId)) {
      return await _stale(owner, restored);
    }
    if (privacy['recording_paused'] == true) {
      await _pauseNativeFailClosed(owner);
      return PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.privacyPaused,
        ownerUserId: owner,
        sessionRestored: restored,
      );
    }

    // Restart is deliberately narrower than delivery. Existing durable samples may be
    // delivered while the producer is stopped; starting production additionally requires
    // the native explicit-enable + permission + location-services gate and a persisted
    // recovery hint (iOS relaunch / Android scheduled recovery).
    var producerRecoveryBlocked = false;
    if (allowProducerResume && nativeStatus.restorePending) {
      if (!nativeStatus.canStart) {
        producerRecoveryBlocked = true;
      } else {
        try {
          nativeStatus = await _locationBridge.start(owner);
          producerRecoveryBlocked =
              nativeStatus.runtime != NativeLocationRuntime.running;
        } on MissingPluginException {
          producerRecoveryBlocked = true;
        } on PlatformException {
          // Android may legally deny a background FGS start even after WorkManager wakes.
          // Do not bypass that platform decision; durable backlog delivery remains allowed.
          producerRecoveryBlocked = true;
        }
        if (!await _authorityStillPersisted(owner, generation, sessionId)) {
          await _pauseNativeFailClosed(owner);
          return await _stale(owner, restored);
        }
      }
    }

    final lease = await _store.tryAcquireLocationDeliveryLease(owner);
    if (lease == null) {
      return PassiveMemoryRecoveryReport(
        status: PassiveMemoryRecoveryStatus.busy,
        ownerUserId: owner,
        sessionRestored: restored,
      );
    }

    var handedOff = 0;
    try {
      if (!await _authorityStillPersisted(owner, generation, sessionId)) {
        return await _stale(owner, restored);
      }

      handedOff = await _handoffNative(
        owner,
        generation,
        sessionId,
        onNativeSamples: onNativeSamples,
      );
      if (!await _authorityStillPersisted(owner, generation, sessionId)) {
        return await _stale(owner, restored);
      }

      final queued = await _store.listLocationSamples(owner, limit: 100);
      if (queued.isEmpty) {
        return PassiveMemoryRecoveryReport(
          status: producerRecoveryBlocked
              ? PassiveMemoryRecoveryStatus.nativeNotEligible
              : PassiveMemoryRecoveryStatus.noWork,
          ownerUserId: owner,
          nativeHandedOff: handedOff,
          sessionRestored: restored,
        );
      }
      if (!forceDelivery) {
        final oldestAge =
            DateTime.now().toUtc().difference(queued.first.recordedAt);
        if (queued.length < minimumBatchSize && oldestAge < maxBatchAge) {
          return PassiveMemoryRecoveryReport(
            status: PassiveMemoryRecoveryStatus.deferred,
            ownerUserId: owner,
            nativeHandedOff: handedOff,
            sessionRestored: restored,
          );
        }
      }
      final ids = queued.map((item) => item.clientUuid).toList(growable: false);
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

      await _store.recordLocationDeliveryAttempt(owner, ids);
      if (!await _authorityStillPersisted(owner, generation, sessionId)) {
        return await _stale(owner, restored);
      }

      try {
        final result = await _api.uploadLocationBatch(points);
        // A late success may have reached the server after logout/account switch. UUID
        // idempotency makes replay safe; never delete owner A's local proof until the
        // initiating AUTH-001 generation is still current.
        if (!await _authorityStillPersisted(owner, generation, sessionId)) {
          return await _stale(owner, restored);
        }
        if (result.terminalCount != points.length) {
          await _store.recordLocationDeliveryFailure(
            owner,
            ids,
            'incomplete_location_batch_receipt',
          );
          await _recordNativeDeliveryFailure(
            owner,
            'incomplete_location_batch_receipt',
          );
          return PassiveMemoryRecoveryReport(
            status: PassiveMemoryRecoveryStatus.retryableFailure,
            ownerUserId: owner,
            nativeHandedOff: handedOff,
            deliveryAttempted: points.length,
            sessionRestored: restored,
          );
        }
        await _store.deleteLocationSamples(owner, ids);
        try {
          await _samplingBridge.recordUploadBatch(
            owner,
            sampleCount: points.length,
          );
        } on MissingPluginException {
          // Metrics are advisory; authoritative SQLite/server delivery is already complete.
        } on PlatformException {
          // Same: never recreate delivered rows because diagnostics failed.
        }
        return PassiveMemoryRecoveryReport(
          status: PassiveMemoryRecoveryStatus.delivered,
          ownerUserId: owner,
          nativeHandedOff: handedOff,
          deliveryAttempted: points.length,
          deliveryCompleted: points.length,
          sessionRestored: restored,
        );
      } on TransportException catch (error) {
        if (await _authorityStillPersisted(owner, generation, sessionId)) {
          await _store.recordLocationDeliveryFailure(owner, ids, error.message);
          await _recordNativeDeliveryFailure(owner, error.message);
        }
        return PassiveMemoryRecoveryReport(
          status: PassiveMemoryRecoveryStatus.retryableFailure,
          ownerUserId: owner,
          nativeHandedOff: handedOff,
          deliveryAttempted: points.length,
          sessionRestored: restored,
        );
      } on ApiException catch (error) {
        if (!await _authorityStillPersisted(owner, generation, sessionId)) {
          return await _stale(owner, restored);
        }
        if (error.statusCode == 409 && error.message == 'RECORDING_PAUSED') {
          await _store.recordLocationDeliveryFailure(
            owner,
            ids,
            'RECORDING_PAUSED',
          );
          await _recordNativeDeliveryFailure(owner, 'RECORDING_PAUSED');
          await _pauseNativeFailClosed(owner);
          return PassiveMemoryRecoveryReport(
            status: PassiveMemoryRecoveryStatus.privacyPaused,
            ownerUserId: owner,
            nativeHandedOff: handedOff,
            deliveryAttempted: points.length,
            sessionRestored: restored,
          );
        }
        if (error.statusCode == 401) {
          final failureReason = 'HTTP 401: ${error.message}';
          await _store.recordLocationDeliveryFailure(owner, ids, failureReason);
          await _recordNativeDeliveryFailure(owner, failureReason);
          await _disableNativeFailClosed(owner);
          return PassiveMemoryRecoveryReport(
            status: PassiveMemoryRecoveryStatus.noSession,
            ownerUserId: owner,
            nativeHandedOff: handedOff,
            deliveryAttempted: points.length,
            sessionRestored: restored,
          );
        }
        final retryable = error.statusCode == 403 ||
            error.statusCode == 408 ||
            error.statusCode == 429 ||
            error.statusCode >= 500 ||
            (error.statusCode == 422 &&
                error.message == 'LOCATION_RECORDED_AT_IN_FUTURE');
        final failureReason = 'HTTP ${error.statusCode}: ${error.message}';
        await _store.recordLocationDeliveryFailure(owner, ids, failureReason);
        await _recordNativeDeliveryFailure(owner, failureReason);
        if (!retryable) {
          await _store.blockLocationSamples(
            owner,
            ids,
            'HTTP ${error.statusCode}: ${error.message}',
          );
        }
        return PassiveMemoryRecoveryReport(
          status: retryable
              ? PassiveMemoryRecoveryStatus.retryableFailure
              : PassiveMemoryRecoveryStatus.blockedFailure,
          ownerUserId: owner,
          nativeHandedOff: handedOff,
          deliveryAttempted: points.length,
          sessionRestored: restored,
        );
      } on ProtocolException catch (error) {
        if (await _authorityStillPersisted(owner, generation, sessionId)) {
          await _store.recordLocationDeliveryFailure(owner, ids, error.message);
          await _recordNativeDeliveryFailure(owner, error.message);
        }
        return PassiveMemoryRecoveryReport(
          status: PassiveMemoryRecoveryStatus.retryableFailure,
          ownerUserId: owner,
          nativeHandedOff: handedOff,
          deliveryAttempted: points.length,
          sessionRestored: restored,
        );
      }
    } finally {
      await _store.releaseLocationDeliveryLease(owner, lease);
    }
  }

  Future<int> _handoffNative(
    String owner,
    int generation,
    String sessionId, {
    required void Function(List<NativeLocationSample>)? onNativeSamples,
  }) async {
    List<NativeLocationSample> samples;
    try {
      samples = await _samplingBridge.drainSamples(owner, limit: 100);
    } on MissingPluginException {
      return 0;
    } on PlatformException {
      return 0;
    }
    if (!await _authorityStillPersisted(owner, generation, sessionId)) return 0;

    if (onNativeSamples != null && samples.isNotEmpty) {
      try {
        onNativeSamples(List<NativeLocationSample>.unmodifiable(samples));
      } catch (_) {
        // Motion/adaptive observers are advisory and must never block durable handoff.
      }
    }

    final acknowledged = <String>[];
    var sqliteCapacityBlocked = false;
    for (final sample in samples) {
      if (!_authorityCurrent(owner, generation)) break;
      try {
        await _store.enqueueLocationSample(
          ownerUserId: owner,
          clientUuid: sample.clientUuid,
          latitude: sample.latitude,
          longitude: sample.longitude,
          accuracyMeters: sample.accuracyMeters,
          speedMetersPerSecond: sample.speedMetersPerSecond,
          recordedAt: sample.recordedAt,
        );
      } on LocationQueueCapacityException {
        // Do not ACK the current or later native rows. The bounded native queue remains
        // their durable authority until SQLite/server delivery makes space again.
        sqliteCapacityBlocked = true;
        break;
      }
      acknowledged.add(sample.clientUuid);
    }

    if (sqliteCapacityBlocked) {
      await _recordNativeDeliveryFailure(owner, 'sqlite_queue_capacity');
    }

    if (acknowledged.isNotEmpty &&
        await _authorityStillPersisted(owner, generation, sessionId)) {
      try {
        // Native deletion occurs only after every acknowledged UUID has committed to SQLite.
        await _samplingBridge.acknowledgeSamples(owner, acknowledged);
      } on MissingPluginException {
        // Safe replay: SQLite uniqueness preserves the same UUID on the next drain.
      } on PlatformException {
        // Same safe replay boundary.
      }
    }
    return acknowledged.length;
  }

  bool _authorityCurrent(String owner, int generation) =>
      _api.authenticatedUserId == owner && _api.sessionVersion == generation;

  Future<bool> _authorityStillPersisted(
    String owner,
    int generation,
    String sessionId,
  ) async {
    if (!_authorityCurrent(owner, generation) ||
        _api.authenticatedSessionId != sessionId) {
      return false;
    }
    try {
      final matches = await _api.currentSessionMatchesSecureStorage();
      return matches &&
          _authorityCurrent(owner, generation) &&
          _api.authenticatedSessionId == sessionId;
    } catch (_) {
      // Secure-storage uncertainty is never permission to publish owner-bound data.
      return false;
    }
  }

  Future<PassiveMemoryRecoveryReport> _stale(
    String owner,
    bool restored,
  ) async {
    // A stale generation/session can be an account switch or logout racing an async
    // response. Stop production for the old owner, but preserve the user's explicit
    // automatic-enable preference as a quarantine unless terminal auth loss was proven.
    await _pauseNativeFailClosed(owner);
    return PassiveMemoryRecoveryReport(
      status: PassiveMemoryRecoveryStatus.authorityChanged,
      ownerUserId: owner,
      sessionRestored: restored,
    );
  }

  Future<void> _recordNativeDeliveryFailure(
    String owner,
    String reason,
  ) async {
    if (_samplingBridge is! NativeDeliveryDiagnosticsSink) return;
    final bridge = _samplingBridge as NativeDeliveryDiagnosticsSink;
    try {
      await bridge.recordDeliveryFailure(owner, reason: reason);
    } on MissingPluginException {
      // SQLite diagnostics remain authoritative for delivery retry state.
    } on PlatformException {
      // Native metrics are best-effort and never alter durable queue semantics.
    }
  }

  Future<void> _disableNativeFailClosed(String owner) async {
    try {
      await _locationBridge.disableAutomaticLocation(owner);
    } on MissingPluginException {
      // Auth loss still blocks upload even when native control is unavailable.
    } on PlatformException {
      // Same fail-closed network/publication boundary.
    }
  }

  Future<void> _pauseNativeFailClosed(String owner) async {
    try {
      await _locationBridge.pause(owner);
    } on MissingPluginException {
      // Native relaunch paths already default to stopped; this is best-effort convergence.
    } on PlatformException {
      // Same fail-closed semantics: no upload proceeds after this point.
    }
  }
}
