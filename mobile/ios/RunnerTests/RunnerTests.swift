import Flutter
import UIKit
import XCTest
@testable import Runner

class RunnerTests: XCTestCase {
  private let owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

  func testRecordingHealthRuntimeProjectionIsTruthful() {
    XCTAssertEqual(
      NativeLocationPolicy.recordingHealthBackgroundRuntime(
        authorization: .background,
        locationServicesEnabled: true
      ),
      "eligible"
    )
    XCTAssertEqual(
      NativeLocationPolicy.recordingHealthBackgroundRuntime(
        authorization: .foreground,
        locationServicesEnabled: true
      ),
      "unknown"
    )
    XCTAssertEqual(
      NativeLocationPolicy.recordingHealthBackgroundRuntime(
        authorization: .background,
        locationServicesEnabled: false
      ),
      "unknown"
    )
  }

  func testLocationStartRequiresAlwaysPermissionAndMatchingOwner() {
    XCTAssertTrue(
      NativeLocationPolicy.canStart(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true
      )
    )
    XCTAssertFalse(
      NativeLocationPolicy.canStart(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .foreground,
        locationServicesEnabled: true
      )
    )
    XCTAssertFalse(
      NativeLocationPolicy.canStart(
        ownerUserId: owner,
        enabledOwnerUserId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        authorization: .background,
        locationServicesEnabled: true
      )
    )
  }

  func testAlwaysPermissionOnlyFollowsExplicitEnableWithForegroundGrant() {
    XCTAssertFalse(
      NativeLocationPolicy.shouldRequestAlways(
        explicitAutomaticEnable: false,
        authorization: .foreground
      )
    )
    XCTAssertFalse(
      NativeLocationPolicy.shouldRequestAlways(
        explicitAutomaticEnable: true,
        authorization: .notDetermined
      )
    )
    XCTAssertTrue(
      NativeLocationPolicy.shouldRequestAlways(
        explicitAutomaticEnable: true,
        authorization: .foreground
      )
    )
  }

  func testPermissionRevocationStopsRunningProducer() {
    XCTAssertEqual(
      NativeLocationPolicy.reconcileRuntime(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .foreground,
        locationServicesEnabled: true,
        runtime: .running,
        nativeProducerActive: true
      ),
      .stopped
    )
    XCTAssertEqual(
      NativeLocationPolicy.reconcileRuntime(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: false,
        runtime: .running,
        nativeProducerActive: true
      ),
      .stopped
    )
  }

  func testLocationRelaunchMarksPendingButKeepsProducerStoppedUntilPrivacyVerification() {
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .running
      ),
      NativeLocationRelaunchState(
        restorePending: true,
        runtime: .paused
      )
    )
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: owner,
        authorization: .foreground,
        locationServicesEnabled: true,
        runtime: .running
      ),
      NativeLocationRelaunchState(
        restorePending: false,
        runtime: .stopped
      )
    )
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .running
      ),
      NativeLocationRelaunchState(
        restorePending: false,
        runtime: .stopped
      )
    )
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .paused
      ),
      NativeLocationRelaunchState(
        restorePending: false,
        runtime: .stopped
      )
    )
  }

  func testMotionSamplingProfileRejectsFiveSecondLoopAndInvalidThresholds() {
    XCTAssertNil(
      NativeSamplingProfile.validated(
        motionState: .walking,
        minIntervalMs: 5_000,
        minDistanceMeters: 20,
        maxAccuracyMeters: 80
      )
    )
    XCTAssertNil(
      NativeSamplingProfile.validated(
        motionState: .walking,
        minIntervalMs: 60_000,
        minDistanceMeters: 1,
        maxAccuracyMeters: 80
      )
    )
    XCTAssertEqual(
      NativeSamplingProfile.validated(
        motionState: .vehicle,
        minIntervalMs: 30_000,
        minDistanceMeters: 100,
        maxAccuracyMeters: 100
      ),
      NativeSamplingProfile(
        motionState: .vehicle,
        minIntervalMs: 30_000,
        minDistanceMeters: 100,
        maxAccuracyMeters: 100
      )
    )
  }

  func testNativeRawQueueQuotaIsOwnerLocal() {
    let ownerB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    let samples = (0..<1000).map { index in
      NativeQueuedLocationSample(
        ownerUserId: owner,
        clientUuid: "sample-\(index)",
        latitude: 0,
        longitude: 0,
        accuracyMeters: 20,
        speedMetersPerSecond: 0,
        recordedAtMillis: Int64(index)
      )
    }

    // [人工注释][S2-004/005] A full owner A queue cannot consume owner B's quota.
    XCTAssertFalse(
      NativeOwnerQueueQuota.hasCapacity(
        samples: samples,
        ownerUserId: owner,
        maxPerOwner: 1000
      )
    )
    XCTAssertTrue(
      NativeOwnerQueueQuota.hasCapacity(
        samples: samples,
        ownerUserId: ownerB,
        maxPerOwner: 1000
      )
    )
  }

  func testMotionSignalMappingAndCadenceGateAreDeterministic() {
    XCTAssertNil(NativeMotionSignalMapper.normalizedSpeed(-1))
    XCTAssertEqual(NativeMotionSignalMapper.normalizedSpeed(2.5), 2.5)
    XCTAssertNil(NativeMotionSignalMapper.normalizedAccuracy(-1))
    XCTAssertEqual(NativeMotionSignalMapper.normalizedAccuracy(18), 18)

    XCTAssertTrue(
      NativeLocationSampleAdmission.cadenceAllows(
        previousRecordedAtMillis: nil,
        candidateRecordedAtMillis: 10_000,
        minIntervalMs: 60_000
      )
    )
    XCTAssertFalse(
      NativeLocationSampleAdmission.cadenceAllows(
        previousRecordedAtMillis: 10_000,
        candidateRecordedAtMillis: 50_000,
        minIntervalMs: 60_000
      )
    )
    XCTAssertTrue(
      NativeLocationSampleAdmission.cadenceAllows(
        previousRecordedAtMillis: 10_000,
        candidateRecordedAtMillis: 70_000,
        minIntervalMs: 60_000
      )
    )

    XCTAssertTrue(
      NativeLocationSampleAdmission.accepts(
        accuracyMeters: nil,
        profile: .fallback
      )
    )
    XCTAssertFalse(
      NativeLocationSampleAdmission.accepts(
        accuracyMeters: 180,
        profile: .fallback
      )
    )
  }

  func testInactiveNativeProducerCannotRemainRunning() {
    XCTAssertEqual(
      NativeLocationPolicy.reconcileRuntime(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .running,
        nativeProducerActive: false
      ),
      .stopped
    )
  }

  func testLegacyNativeQueueSampleDecodesIntoV2WithoutChangingCapturedIdentity() throws {
    let legacy: [String: Any] = [
      "ownerUserId": owner,
      "clientUuid": "11111111-1111-4111-8111-111111111111",
      "latitude": 3.139,
      "longitude": 101.6869,
      "accuracyMeters": 18.0,
      "speedMetersPerSecond": 1.5,
      "recordedAtMillis": 1_790_820_000_000 as Int64,
    ]
    let data = try JSONSerialization.data(withJSONObject: legacy)
    let decoded = try JSONDecoder().decode(
      NativeQueuedLocationSample.self,
      from: data
    )

    XCTAssertEqual(decoded.ownerUserId, owner)
    XCTAssertEqual(decoded.clientUuid, "11111111-1111-4111-8111-111111111111")
    XCTAssertEqual(decoded.recordedAtMillis, 1_790_820_000_000)
    XCTAssertEqual(decoded.queueSequence, 0)
    XCTAssertEqual(decoded.enqueuedAtMillis, decoded.recordedAtMillis)
    XCTAssertEqual(decoded.handoffAttemptCount, 0)
  }

  func testNativeQueueV2MetadataSurvivesRoundTrip() throws {
    let sample = NativeQueuedLocationSample(
      ownerUserId: owner,
      clientUuid: "22222222-2222-4222-8222-222222222222",
      latitude: 3.139,
      longitude: 101.6869,
      accuracyMeters: 18,
      speedMetersPerSecond: 1.5,
      recordedAtMillis: 1_790_820_000_000,
      queueSequence: 42,
      enqueuedAtMillis: 1_790_820_001_000,
      handoffAttemptCount: 3
    )

    let decoded = try JSONDecoder().decode(
      NativeQueuedLocationSample.self,
      from: JSONEncoder().encode(sample)
    )
    XCTAssertEqual(decoded.queueSequence, 42)
    XCTAssertEqual(decoded.enqueuedAtMillis, 1_790_820_001_000)
    XCTAssertEqual(decoded.handoffAttemptCount, 3)
    XCTAssertEqual(decoded.clientUuid, sample.clientUuid)
  }

}
