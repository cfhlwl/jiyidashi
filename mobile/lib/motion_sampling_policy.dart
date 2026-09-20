enum MotionState {
  unknown,
  stationary,
  walking,
  vehicle,
}

class MotionObservation {
  const MotionObservation({
    required this.recordedAt,
    this.speedMetersPerSecond,
    this.accuracyMeters,
  });

  final DateTime recordedAt;
  final double? speedMetersPerSecond;
  final double? accuracyMeters;
}

/// Converts noisy platform speed/accuracy signals into a small deterministic state machine.
/// A single contradictory fix cannot flip an established state; poor/unknown observations
/// need three consecutive confirmations before degrading to unknown.
class MotionStateMachine {
  MotionStateMachine({MotionState initialState = MotionState.unknown})
      : _state = initialState;

  MotionState _state;
  MotionState? _candidate;
  int _candidateStreak = 0;

  MotionState get state => _state;

  MotionState observe(MotionObservation observation) {
    final classified = classify(observation);
    if (classified == _state) {
      _candidate = null;
      _candidateStreak = 0;
      return _state;
    }

    if (_state == MotionState.unknown && classified != MotionState.unknown) {
      _state = classified;
      _candidate = null;
      _candidateStreak = 0;
      return _state;
    }

    if (_candidate == classified) {
      _candidateStreak += 1;
    } else {
      _candidate = classified;
      _candidateStreak = 1;
    }

    final required = classified == MotionState.unknown ? 3 : 2;
    if (_candidateStreak >= required) {
      _state = classified;
      _candidate = null;
      _candidateStreak = 0;
    }
    return _state;
  }

  static MotionState classify(MotionObservation observation) {
    final accuracy = observation.accuracyMeters;
    if (accuracy != null && (accuracy.isNaN || accuracy > 150)) {
      return MotionState.unknown;
    }
    final speed = observation.speedMetersPerSecond;
    if (speed == null || speed.isNaN || speed < 0) {
      return MotionState.unknown;
    }
    if (speed < 0.8) return MotionState.stationary;
    if (speed < 6.5) return MotionState.walking;
    return MotionState.vehicle;
  }
}

class AdaptiveSamplingProfile {
  const AdaptiveSamplingProfile({
    required this.motionState,
    required this.minInterval,
    required this.minDistanceMeters,
    required this.maxAcceptedAccuracyMeters,
    required this.batchTarget,
    required this.maxBatchAge,
  });

  final MotionState motionState;
  final Duration minInterval;
  final double minDistanceMeters;
  final double maxAcceptedAccuracyMeters;
  final int batchTarget;
  final Duration maxBatchAge;

  @override
  bool operator ==(Object other) {
    return other is AdaptiveSamplingProfile &&
        other.motionState == motionState &&
        other.minInterval == minInterval &&
        other.minDistanceMeters == minDistanceMeters &&
        other.maxAcceptedAccuracyMeters == maxAcceptedAccuracyMeters &&
        other.batchTarget == batchTarget &&
        other.maxBatchAge == maxBatchAge;
  }

  @override
  int get hashCode => Object.hash(
        motionState,
        minInterval,
        minDistanceMeters,
        maxAcceptedAccuracyMeters,
        batchTarget,
        maxBatchAge,
      );
}

class AdaptiveSamplingPolicy {
  const AdaptiveSamplingPolicy();

  AdaptiveSamplingProfile profileFor({
    required MotionState motionState,
    double? recentAccuracyMeters,
  }) {
    final base = switch (motionState) {
      MotionState.stationary => const AdaptiveSamplingProfile(
          motionState: MotionState.stationary,
          minInterval: Duration(minutes: 5),
          minDistanceMeters: 150,
          maxAcceptedAccuracyMeters: 120,
          batchTarget: 6,
          maxBatchAge: Duration(minutes: 15),
        ),
      MotionState.walking => const AdaptiveSamplingProfile(
          motionState: MotionState.walking,
          minInterval: Duration(minutes: 1),
          minDistanceMeters: 40,
          maxAcceptedAccuracyMeters: 80,
          batchTarget: 6,
          maxBatchAge: Duration(minutes: 5),
        ),
      MotionState.vehicle => const AdaptiveSamplingProfile(
          motionState: MotionState.vehicle,
          minInterval: Duration(seconds: 30),
          minDistanceMeters: 100,
          maxAcceptedAccuracyMeters: 100,
          batchTarget: 10,
          maxBatchAge: Duration(minutes: 3),
        ),
      MotionState.unknown => const AdaptiveSamplingProfile(
          motionState: MotionState.unknown,
          minInterval: Duration(minutes: 2),
          minDistanceMeters: 75,
          maxAcceptedAccuracyMeters: 120,
          batchTarget: 6,
          maxBatchAge: Duration(minutes: 5),
        ),
    };

    final accuracy = recentAccuracyMeters;
    if (accuracy == null || accuracy <= 80) return base;

    // Poor recent fixes should not cause the client to wake/upload more aggressively while
    // trying to "chase" precision. Back off interval/distance but keep a finite quality cap.
    return AdaptiveSamplingProfile(
      motionState: base.motionState,
      minInterval: Duration(
        milliseconds: base.minInterval.inMilliseconds * 2,
      ),
      minDistanceMeters: base.minDistanceMeters * 1.5,
      maxAcceptedAccuracyMeters:
          base.maxAcceptedAccuracyMeters < 150 ? 150 : base.maxAcceptedAccuracyMeters,
      batchTarget: base.batchTarget,
      maxBatchAge: base.maxBatchAge,
    );
  }
}
