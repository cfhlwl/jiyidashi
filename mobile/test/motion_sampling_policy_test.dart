import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/motion_sampling_policy.dart';

void main() {
  test('motion state transitions require deterministic confirmation', () {
    final machine = MotionStateMachine();
    final at = DateTime.utc(2026, 9, 20, 1);

    expect(
      machine.observe(
        MotionObservation(
          recordedAt: at,
          speedMetersPerSecond: 0.2,
          accuracyMeters: 12,
        ),
      ),
      MotionState.stationary,
    );

    expect(
      machine.observe(
        MotionObservation(
          recordedAt: at.add(const Duration(minutes: 1)),
          speedMetersPerSecond: 1.8,
          accuracyMeters: 15,
        ),
      ),
      MotionState.stationary,
      reason: 'one contradictory fix must not flip established state',
    );
    expect(
      machine.observe(
        MotionObservation(
          recordedAt: at.add(const Duration(minutes: 2)),
          speedMetersPerSecond: 1.6,
          accuracyMeters: 15,
        ),
      ),
      MotionState.walking,
    );

    expect(
      machine.observe(
        MotionObservation(
          recordedAt: at.add(const Duration(minutes: 3)),
          speedMetersPerSecond: 14,
          accuracyMeters: 20,
        ),
      ),
      MotionState.walking,
    );
    expect(
      machine.observe(
        MotionObservation(
          recordedAt: at.add(const Duration(minutes: 4)),
          speedMetersPerSecond: 12,
          accuracyMeters: 20,
        ),
      ),
      MotionState.vehicle,
    );
  });

  test('poor observations need three confirmations before degrading to unknown', () {
    final machine = MotionStateMachine(initialState: MotionState.walking);
    final at = DateTime.utc(2026, 9, 20, 1);

    for (var index = 0; index < 2; index += 1) {
      expect(
        machine.observe(
          MotionObservation(
            recordedAt: at.add(Duration(minutes: index)),
            speedMetersPerSecond: 2,
            accuracyMeters: 250,
          ),
        ),
        MotionState.walking,
      );
    }
    expect(
      machine.observe(
        MotionObservation(
          recordedAt: at.add(const Duration(minutes: 2)),
          speedMetersPerSecond: 2,
          accuracyMeters: 250,
        ),
      ),
      MotionState.unknown,
    );
  });

  test('adaptive profiles are motion-aware and never use a five-second loop', () {
    const policy = AdaptiveSamplingPolicy();

    final stationary = policy.profileFor(motionState: MotionState.stationary);
    final walking = policy.profileFor(motionState: MotionState.walking);
    final vehicle = policy.profileFor(motionState: MotionState.vehicle);

    expect(stationary.minInterval, const Duration(minutes: 5));
    expect(walking.minInterval, const Duration(minutes: 1));
    expect(vehicle.minInterval, const Duration(seconds: 30));
    expect(stationary.minDistanceMeters, greaterThan(walking.minDistanceMeters));
    expect(
      [stationary, walking, vehicle]
          .every((profile) => profile.minInterval >= const Duration(seconds: 15)),
      isTrue,
    );
  });

  test('poor recent accuracy backs off rather than increasing wake frequency', () {
    const policy = AdaptiveSamplingPolicy();
    final normal = policy.profileFor(
      motionState: MotionState.walking,
      recentAccuracyMeters: 20,
    );
    final poor = policy.profileFor(
      motionState: MotionState.walking,
      recentAccuracyMeters: 120,
    );

    expect(poor.minInterval, normal.minInterval * 2);
    expect(poor.minDistanceMeters, normal.minDistanceMeters * 1.5);
    expect(
      poor.maxAcceptedAccuracyMeters,
      greaterThanOrEqualTo(normal.maxAcceptedAccuracyMeters),
    );
  });
}
