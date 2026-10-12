import Flutter
import UIKit
import XCTest
import WechatOpenSDK
@testable import Runner

class RunnerTests: XCTestCase {
  private let owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

  func testPhoneOneTapNativeAdapterFailsClosedBeforePNVSConfiguration() {
    let adapter = FailClosedPhoneOneTapProviderAdapter()
    var result: PhoneOneTapNativeResult?
    adapter.initialize(privacyConsentGranted: false) { result = $0 }
    XCTAssertEqual(result?.state, .unavailable)
    XCTAssertEqual(
      result?.reason,
      "PRIVACY_NOT_ACCEPTED"
    )
    adapter.initialize(privacyConsentGranted: true) { result = $0 }
    XCTAssertEqual(
      result?.reason,
      "PNVS_NOT_CONFIGURED"
    )
    adapter.checkAvailability { result = $0 }
    adapter.requestLoginToken(viewController: UIViewController()) { result = $0 }
    XCTAssertEqual(result?.state, .unavailable)
  }

  func testPhoneOneTapProductionConfigurationMissingFailsClosed() {
    let adapter = FailClosedPhoneOneTapProviderAdapter(
      configuration: PhoneOneTapProviderConfiguration(
        schemeIdentifier: nil,
        productionRequired: true
      )
    )
    var result: PhoneOneTapNativeResult?

    adapter.initialize(privacyConsentGranted: true) { result = $0 }

    XCTAssertEqual(result?.state, .unavailable)
    XCTAssertEqual(result?.reason, "PNVS_CONFIGURATION_MISSING")
  }

  func testConfiguredSchemeDoesNotEnableUnavailableProvider() {
    let adapter = FailClosedPhoneOneTapProviderAdapter(
      configuration: PhoneOneTapProviderConfiguration(
        schemeIdentifier: "test-scheme-id",
        productionRequired: true
      )
    )
    var result: PhoneOneTapNativeResult?

    adapter.initialize(privacyConsentGranted: true) { result = $0 }

    XCTAssertEqual(result?.state, .unavailable)
    XCTAssertEqual(result?.reason, "PNVS_NOT_CONFIGURED")
  }

  func testPhoneOneTapRequestGateFencesRepeatedAndLateCallbacks() {
    let gate = PhoneOneTapRequestGate()
    let first = gate.begin()

    XCTAssertNotNil(first)
    XCTAssertNil(gate.begin())
    XCTAssertTrue(gate.isCurrent(first!))
    XCTAssertFalse(gate.finish(first! + 1))
    XCTAssertTrue(gate.hasActiveRequest)
    XCTAssertTrue(gate.finish(first!))
    XCTAssertFalse(gate.hasActiveRequest)
    XCTAssertFalse(gate.finish(first!))
  }

  func testPhoneOneTapLifecycleInvalidatesOldCallback() {
    let gate = PhoneOneTapRequestGate()
    let first = gate.begin()!

    gate.invalidate()

    XCTAssertFalse(gate.isCurrent(first))
    XCTAssertFalse(gate.finish(first))
  }

  func testPhoneOneTapAsyncCallbackCompletesOnce() {
    let gate = PhoneOneTapRequestGate()
    let generation = gate.begin()!
    var completions = 0
    let callback = PhoneOneTapCallbackFence(gate: gate, generation: generation) { _ in
      completions += 1
    }
    let value = PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "opaque")

    XCTAssertTrue(callback.complete(value))
    XCTAssertFalse(callback.complete(value))
    XCTAssertEqual(completions, 1)
  }

  func testPhoneOneTapPrivacyRevocationIsFailClosed() {
    let adapter = FailClosedPhoneOneTapProviderAdapter()
    var result: PhoneOneTapNativeResult?

    adapter.revokePrivacy { result = $0 }

    XCTAssertEqual(result?.state, .unavailable)
    XCTAssertEqual(result?.reason, "PRIVACY_REVOKED")
  }

  func testPhoneOneTapBridgeUsesRequestScopedControllerAndFencesAsyncLifecycle() {
    let adapter = DelayedPhoneOneTapAdapter()
    var host: UIViewController? = UIViewController()
    let bridge = PhoneOneTapNativeBridge(
      adapter: adapter,
      viewControllerProvider: { host }
    )

    var initializeResult: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { value in initializeResult = value as? [String: Any] }
    )
    adapter.initializeCompletion?(
      PhoneOneTapNativeResult(state: .available)
    )
    XCTAssertEqual(initializeResult?["state"] as? String, "AVAILABLE")

    let controllerA = host!
    var firstResult: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in if let value = value as? [String: Any] { firstResult.append(value) } }
    )
    XCTAssertTrue(adapter.requestedControllers.last === controllerA)

    bridge.invalidateForLifecycle(reason: "VIEW_CONTROLLER_REPLACED")
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "late-a")
    )
    XCTAssertEqual(firstResult.count, 1)
    XCTAssertEqual(firstResult.first?["reason"] as? String, "VIEW_CONTROLLER_REPLACED")

    host = UIViewController()
    var reinitializeResult: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { value in reinitializeResult = value as? [String: Any] }
    )
    adapter.initializeCompletion?(
      PhoneOneTapNativeResult(state: .available)
    )
    XCTAssertEqual(reinitializeResult?["state"] as? String, "AVAILABLE")

    var secondResult: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in if let value = value as? [String: Any] { secondResult.append(value) } }
    )
    XCTAssertTrue(adapter.requestedControllers.last === host)
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "token-b")
    )
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "duplicate-b")
    )
    XCTAssertEqual(secondResult.count, 1)
    XCTAssertEqual(secondResult.first?["login_token"] as? String, "token-b")
  }

  func testPhoneOneTapBridgePrivacyRevocationCancelsPendingAndIgnoresLateCallback() {
    let adapter = DelayedPhoneOneTapAdapter()
    let host = UIViewController()
    let bridge = PhoneOneTapNativeBridge(
      adapter: adapter,
      viewControllerProvider: { host }
    )
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { _ in }
    )
    adapter.initializeCompletion?(
      PhoneOneTapNativeResult(state: .available)
    )

    var requestResults: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in if let value = value as? [String: Any] { requestResults.append(value) } }
    )
    var privacyResult: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": false]
      ),
      result: { value in privacyResult = value as? [String: Any] }
    )
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "late")
    )

    XCTAssertEqual(requestResults.first?["reason"] as? String, "PRIVACY_REVOKED")
    XCTAssertEqual(privacyResult?["reason"] as? String, "PRIVACY_REVOKED")
    XCTAssertEqual(requestResults.count, 1)
    XCTAssertEqual(adapter.revokePrivacyCount, 1)
  }

  func testPhoneOneTapBridgeMissingControllerFailsClosedWithoutProviderCall() {
    let adapter = DelayedPhoneOneTapAdapter()
    let bridge = PhoneOneTapNativeBridge(adapter: adapter)
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { _ in }
    )
    adapter.initializeCompletion?(
      PhoneOneTapNativeResult(state: .available)
    )

    var result: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in result = value as? [String: Any] }
    )

    XCTAssertEqual(result?["reason"] as? String, "VIEW_CONTROLLER_UNAVAILABLE")
    XCTAssertTrue(adapter.requestedControllers.isEmpty)
  }

  func testPhoneOneTapBridgeControllerIdentityFenceRejectsReplacementAndNil() {
    let adapter = DelayedPhoneOneTapAdapter()
    var host: UIViewController? = UIViewController()
    let bridge = PhoneOneTapNativeBridge(
      adapter: adapter,
      viewControllerProvider: { host }
    )
    initializePhoneOneTapBridge(bridge, adapter: adapter)

    var replacementResult: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in if let value = value as? [String: Any] { replacementResult.append(value) } }
    )
    host = UIViewController()
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "rejected-replacement")
    )
    XCTAssertEqual(replacementResult.first?["reason"] as? String, "VIEW_CONTROLLER_CHANGED")
    XCTAssertNil(replacementResult.first?["login_token"])

    initializePhoneOneTapBridge(bridge, adapter: adapter)
    var nilHostResult: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in if let value = value as? [String: Any] { nilHostResult.append(value) } }
    )
    host = nil
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "rejected-nil")
    )
    XCTAssertEqual(nilHostResult.first?["reason"] as? String, "VIEW_CONTROLLER_UNAVAILABLE")
    XCTAssertNil(nilHostResult.first?["login_token"])
  }

  func testPhoneOneTapBridgeExplicitCancelFencesLateProviderToken() {
    let adapter = DelayedPhoneOneTapAdapter()
    let host = UIViewController()
    let bridge = PhoneOneTapNativeBridge(
      adapter: adapter,
      viewControllerProvider: { host }
    )
    initializePhoneOneTapBridge(bridge, adapter: adapter)

    var requestResults: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in if let value = value as? [String: Any] { requestResults.append(value) } }
    )
    var cancelResults: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "cancel", arguments: nil),
      result: { value in if let value = value as? [String: Any] { cancelResults.append(value) } }
    )
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "late-cancel-token")
    )

    XCTAssertEqual(requestResults.count, 1)
    XCTAssertEqual(requestResults.first?["reason"] as? String, "USER_CANCELLED")
    XCTAssertNil(requestResults.first?["login_token"])
    XCTAssertEqual(cancelResults.count, 1)
    XCTAssertEqual(cancelResults.first?["state"] as? String, "CANCELLED")
    XCTAssertEqual(adapter.cancelCount, 1)
  }

  func testPhoneOneTapBridgeAppBackgroundFencesLateProviderToken() {
    let adapter = DelayedPhoneOneTapAdapter()
    let host = UIViewController()
    let bridge = PhoneOneTapNativeBridge(
      adapter: adapter,
      viewControllerProvider: { host }
    )
    initializePhoneOneTapBridge(bridge, adapter: adapter)

    var requestResults: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestLoginToken", arguments: nil),
      result: { value in if let value = value as? [String: Any] { requestResults.append(value) } }
    )
    bridge.invalidateForLifecycle(reason: "APP_BACKGROUND")
    adapter.requestCompletions.last?(
      PhoneOneTapNativeResult(state: .tokenAcquired, loginToken: "late-background-token")
    )

    XCTAssertEqual(requestResults.count, 1)
    XCTAssertEqual(requestResults.first?["reason"] as? String, "APP_BACKGROUND")
    XCTAssertNil(requestResults.first?["login_token"])
    XCTAssertEqual(adapter.cancelCount, 1)
  }

  private func initializePhoneOneTapBridge(
    _ bridge: PhoneOneTapNativeBridge,
    adapter: DelayedPhoneOneTapAdapter
  ) {
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { _ in }
    )
    adapter.initializeCompletion?(
      PhoneOneTapNativeResult(state: .available)
    )
  }

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


  func testNotificationPayloadCanonicalizationFailsClosed() {
    let bridge = NativeNotificationBridge.shared
    let memoryId = "22222222-2222-4222-8222-222222222222"

    let memory = bridge.canonicalPayload([
      "version": 1,
      "destination": "MEMORY",
      "resource_id": memoryId,
      "url": "https://must-not-be-forwarded.example/",
    ])
    XCTAssertEqual(memory?["version"] as? Int, 1)
    XCTAssertEqual(memory?["destination"] as? String, "MEMORY")
    XCTAssertEqual(memory?["resource_id"] as? String, memoryId)
    XCTAssertNil(memory?["url"])

    let unknown = bridge.canonicalPayload([
      "version": 1,
      "destination": "ARBITRARY_URL",
      "resource_id": memoryId,
    ])
    XCTAssertEqual(unknown?["destination"] as? String, "HOME")

    XCTAssertNil(bridge.canonicalPayload([
      "version": 2,
      "destination": "HOME",
    ]))

    let malformedMemory = bridge.canonicalPayload([
      "version": 1,
      "destination": "MEMORY",
      "resource_id": "not-a-uuid",
    ])
    XCTAssertEqual(malformedMemory?["destination"] as? String, "HOME")
    XCTAssertNil(malformedMemory?["resource_id"])
  }


  func testNotificationPermissionMappingAndRegistrationGate() {
    XCTAssertEqual(
      NativeNotificationPolicy.permissionWire(.notDetermined),
      "notDetermined"
    )
    XCTAssertEqual(
      NativeNotificationPolicy.permissionWire(.denied),
      "denied"
    )
    XCTAssertEqual(
      NativeNotificationPolicy.permissionWire(.authorized),
      "authorized"
    )
    XCTAssertEqual(
      NativeNotificationPolicy.permissionWire(.provisional),
      "provisional"
    )
    XCTAssertFalse(NativeNotificationPolicy.mayRegister(.notDetermined))
    XCTAssertFalse(NativeNotificationPolicy.mayRegister(.denied))
    XCTAssertTrue(NativeNotificationPolicy.mayRegister(.authorized))
    XCTAssertTrue(NativeNotificationPolicy.mayRegister(.provisional))
  }

  func testApnsDeviceTokenByteConversionIsStableLowercaseHex() {
    let bytes = Data([0x00, 0x0f, 0xa1, 0xff])
    XCTAssertEqual(
      NativeNotificationPolicy.tokenHex(bytes),
      "000fa1ff"
    )
  }

}

private final class DelayedPhoneOneTapAdapter: PhoneOneTapProviderAdapter {
  var initializeCompletion: PhoneOneTapCompletion?
  var requestedControllers: [UIViewController] = []
  var requestCompletions: [PhoneOneTapCompletion] = []
  var revokePrivacyCount = 0
  var cancelCount = 0

  func initialize(privacyConsentGranted: Bool, completion: @escaping PhoneOneTapCompletion) {
    initializeCompletion = completion
  }

  func checkAvailability(completion: @escaping PhoneOneTapCompletion) {}
  func preLogin(completion: @escaping PhoneOneTapCompletion) {}

  func requestLoginToken(
    viewController: UIViewController,
    completion: @escaping PhoneOneTapCompletion
  ) {
    requestedControllers.append(viewController)
    requestCompletions.append(completion)
  }

  func cancel(completion: @escaping PhoneOneTapCompletion) {
    cancelCount += 1
    completion(PhoneOneTapNativeResult(state: .cancelled))
  }

  func revokePrivacy(completion: @escaping PhoneOneTapCompletion) {
    revokePrivacyCount += 1
    completion(PhoneOneTapNativeResult(state: .unavailable, reason: "PRIVACY_REVOKED"))
  }
}

private final class ManualWechatIOSAuthScheduler: WechatIOSAuthScheduler {
  private var tasks: [Int: () -> Void] = [:]
  private var order: [Int] = []
  private var nextID = 0

  func schedule(after seconds: TimeInterval, _ task: @escaping () -> Void) -> () -> Void {
    nextID += 1
    let id = nextID
    tasks[id] = task
    order.append(id)
    return { [weak self] in self?.tasks[id] = nil }
  }

  var pendingCount: Int { tasks.count }

  func fireLatest() {
    guard let id = order.reversed().first(where: { tasks[$0] != nil }),
          let task = tasks.removeValue(forKey: id)
    else { return }
    task()
  }

  func fireAll() {
    let pending = order.compactMap { tasks.removeValue(forKey: $0) }
    tasks.removeAll()
    pending.forEach { $0() }
  }
}

private final class FakeWechatIOSSDKClient: WechatIOSSDKClientProtocol {
  var registerCalls = 0
  var installed = true
  var supportsAPI = true
  var sendStates: [String] = []
  var sendCompletion: ((Bool) -> Void)?
  var openURLCalls = 0
  var openUniversalLinkCalls = 0

  func registerApp(appId: String, universalLink: String) -> Bool {
    registerCalls += 1
    return true
  }

  func isWXAppInstalled() -> Bool {
    installed
  }

  func isWXAppSupportAPI() -> Bool {
    supportsAPI
  }

  func sendAuthRequest(
    state: String,
    presenter: UIViewController,
    delegate: WXApiDelegate,
    completion: @escaping (Bool) -> Void
  ) {
    sendStates.append(state)
    sendCompletion = completion
  }

  func handleOpenURL(_ url: URL, delegate: WXApiDelegate) -> Bool {
    openURLCalls += 1
    return true
  }

  func handleOpenUniversalLink(
    _ userActivity: NSUserActivity,
    delegate: WXApiDelegate
  ) -> Bool {
    openUniversalLinkCalls += 1
    return true
  }

  func completeSend(_ accepted: Bool) {
    sendCompletion?(accepted)
    sendCompletion = nil
  }
}

final class WechatAuthNativeBridgeTests: XCTestCase {
  private let configuration = WechatIOSConfiguration(
    appId: "wx-test",
    universalLink: "https://example.invalid/wechat/",
    provider: "wechat",
    liveEnabled: true
  )

  private func makeBridge(
    sdk: FakeWechatIOSSDKClient,
    scheduler: ManualWechatIOSAuthScheduler,
    host: UIViewController? = UIViewController()
  ) -> WechatAuthNativeBridge {
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: scheduler,
      viewControllerProvider: { host }
    )
    return bridge
  }

  func testPrivacyFalsePerformsZeroSDKOperations() {
    let sdk = FakeWechatIOSSDKClient()
    let scheduler = ManualWechatIOSAuthScheduler()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: scheduler
    )
    var value: [String: Any]?

    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": false]
      ),
      result: { value = $0 as? [String: Any] }
    )

    XCTAssertEqual(value?["state"] as? String, "UNAVAILABLE")
    XCTAssertEqual(value?["reason"] as? String, "PRIVACY_REVOKED")
    XCTAssertEqual(sdk.registerCalls, 0)
    XCTAssertTrue(sdk.sendStates.isEmpty)
  }

  func testMissingConfigurationFailsClosedBeforeSDKRegistration() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = WechatAuthNativeBridge(
      configuration: WechatIOSConfiguration(
        appId: nil,
        universalLink: nil,
        provider: "disabled",
        liveEnabled: false
      ),
      sdk: sdk,
      scheduler: ManualWechatIOSAuthScheduler()
    )
    var value: [String: Any]?

    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { value = $0 as? [String: Any] }
    )

    XCTAssertEqual(value?["state"] as? String, "UNAVAILABLE")
    XCTAssertEqual(value?["reason"] as? String, "WECHAT_PROVIDER_DISABLED")
    XCTAssertEqual(sdk.registerCalls, 0)
  }

  func testConfiguredInitializationAndAvailabilityUseProviderNeutralContract() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: ManualWechatIOSAuthScheduler(),
      viewControllerProvider: { UIViewController() }
    )
    var initializeValue: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { initializeValue = $0 as? [String: Any] }
    )
    XCTAssertEqual(initializeValue?["state"] as? String, "AVAILABLE")
    XCTAssertEqual(sdk.registerCalls, 1)

    var availabilityValue: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(methodName: "checkAvailability", arguments: nil),
      result: { availabilityValue = $0 as? [String: Any] }
    )
    XCTAssertEqual(availabilityValue?["state"] as? String, "AVAILABLE")
  }

  func testRequestRechecksProviderAvailabilityAfterPriorProbe() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = makeBridge(sdk: sdk, scheduler: ManualWechatIOSAuthScheduler())
    initializeWechatBridge(bridge)

    var availability: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(methodName: "checkAvailability", arguments: nil),
      result: { availability = $0 as? [String: Any] }
    )
    XCTAssertEqual(availability?["state"] as? String, "AVAILABLE")

    sdk.installed = false
    var request: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { request = $0 as? [String: Any] }
    )
    XCTAssertEqual(request?["reason"] as? String, "WECHAT_NOT_INSTALLED")
    XCTAssertTrue(sdk.sendStates.isEmpty)
  }

  func testMatchingStateProducesOneInMemoryCredentialAndFencesDuplicates() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: ManualWechatIOSAuthScheduler(),
      viewControllerProvider: { UIViewController() }
    )
    initializeWechatBridge(bridge)
    var values: [[String: Any]] = []

    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { values.append(value) } }
    )
    sdk.completeSend(true)
    let state = sdk.sendStates[0]

    bridge.handleProviderResponse(errorCode: 0, state: "wrong", credential: "stale")
    XCTAssertTrue(values.isEmpty)
    bridge.handleProviderResponse(errorCode: 0, state: state, credential: "opaque-code")
    bridge.handleProviderResponse(errorCode: 0, state: state, credential: "duplicate-code")

    XCTAssertEqual(values.count, 1)
    XCTAssertEqual(values[0]["state"] as? String, "CREDENTIAL_ACQUIRED")
    XCTAssertEqual(values[0]["credential"] as? String, "opaque-code")
  }

  func testLateRequestADoesNotAffectRequestB() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: ManualWechatIOSAuthScheduler(),
      viewControllerProvider: { UIViewController() }
    )
    initializeWechatBridge(bridge)
    var first: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { first.append(value) } }
    )
    sdk.completeSend(true)
    let stateA = sdk.sendStates[0]
    var cancel: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(methodName: "cancel", arguments: nil),
      result: { cancel = $0 as? [String: Any] }
    )
    XCTAssertEqual(cancel?["state"] as? String, "CANCELLED")
    XCTAssertEqual(first.first?["reason"] as? String, "USER_CANCELLED")

    var second: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { second.append(value) } }
    )
    sdk.completeSend(true)
    let stateB = sdk.sendStates[1]
    bridge.handleProviderResponse(errorCode: 0, state: stateA, credential: "late-a")
    XCTAssertTrue(second.isEmpty)
    bridge.handleProviderResponse(errorCode: 0, state: stateB, credential: "credential-b")

    XCTAssertEqual(second.count, 1)
    XCTAssertEqual(second[0]["credential"] as? String, "credential-b")
  }

  func testExternalHandoffSuppressesFirstBackgroundButNextBackgroundCancels() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: ManualWechatIOSAuthScheduler(),
      viewControllerProvider: { UIViewController() }
    )
    initializeWechatBridge(bridge)
    var values: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { values.append(value) } }
    )
    sdk.completeSend(true)
    bridge.invalidateForLifecycle(reason: "APP_BACKGROUND")
    XCTAssertTrue(values.isEmpty)
    bridge.markExternalProviderReturned()
    bridge.invalidateForLifecycle(reason: "APP_BACKGROUND")
    XCTAssertEqual(values.first?["state"] as? String, "CANCELLED")
    XCTAssertEqual(values.first?["reason"] as? String, "APP_BACKGROUND")
  }

  func testBackgroundBeforeAsyncHandoffAcceptanceUsesBoundedGrace() {
    let sdk = FakeWechatIOSSDKClient()
    let scheduler = ManualWechatIOSAuthScheduler()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: scheduler,
      handoffAcceptanceGrace: 2,
      viewControllerProvider: { UIViewController() }
    )
    initializeWechatBridge(bridge)
    var values: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { values.append(value) } }
    )

    bridge.invalidateForLifecycle(reason: "APP_BACKGROUND")
    XCTAssertTrue(values.isEmpty)
    XCTAssertEqual(scheduler.pendingCount, 2)

    sdk.completeSend(true)
    XCTAssertTrue(values.isEmpty)
    XCTAssertEqual(scheduler.pendingCount, 1)
  }

  func testBackgroundBeforeHandoffAcceptanceExpiresAndRejectsLateCallback() {
    let sdk = FakeWechatIOSSDKClient()
    let scheduler = ManualWechatIOSAuthScheduler()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: scheduler,
      handoffAcceptanceGrace: 2,
      viewControllerProvider: { UIViewController() }
    )
    initializeWechatBridge(bridge)
    var values: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { values.append(value) } }
    )
    let state = sdk.sendStates[0]

    bridge.invalidateForLifecycle(reason: "APP_BACKGROUND")
    scheduler.fireLatest()
    sdk.completeSend(true)
    bridge.handleProviderResponse(errorCode: 0, state: state, credential: "late")

    XCTAssertEqual(values.count, 1)
    XCTAssertEqual(values[0]["state"] as? String, "CANCELLED")
    XCTAssertEqual(values[0]["reason"] as? String, "APP_BACKGROUND")
  }

  func testPrivacyRevokeCancelsPendingAndIgnoresLateProviderResponse() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: ManualWechatIOSAuthScheduler(),
      viewControllerProvider: { UIViewController() }
    )
    initializeWechatBridge(bridge)
    var values: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { values.append(value) } }
    )
    sdk.completeSend(true)
    let state = sdk.sendStates[0]
    var privacy: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(methodName: "revokePrivacy", arguments: nil),
      result: { privacy = $0 as? [String: Any] }
    )
    bridge.handleProviderResponse(errorCode: 0, state: state, credential: "late")

    XCTAssertEqual(values.count, 1)
    XCTAssertEqual(values[0]["reason"] as? String, "PRIVACY_REVOKED")
    XCTAssertEqual(privacy?["reason"] as? String, "PRIVACY_REVOKED")
  }

  func testMissingPresenterFailsClosedWithoutProviderCall() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = WechatAuthNativeBridge(
      configuration: configuration,
      sdk: sdk,
      scheduler: ManualWechatIOSAuthScheduler(),
      viewControllerProvider: { nil }
    )
    initializeWechatBridge(bridge)
    var value: [String: Any]?
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { value = $0 as? [String: Any] }
    )

    XCTAssertEqual(value?["reason"] as? String, "VIEW_CONTROLLER_UNAVAILABLE")
    XCTAssertTrue(sdk.sendStates.isEmpty)
  }

  func testEngineRebindCancelsOldRequestAndAllowsNewEngineRequest() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = makeBridge(sdk: sdk, scheduler: ManualWechatIOSAuthScheduler())
    initializeWechatBridge(bridge)
    let engineA = NSObject()
    let engineB = NSObject()
    bridge.rebindEngineForTesting(engineA)

    var oldValues: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { oldValues.append(value) } }
    )
    sdk.completeSend(true)
    let stateA = sdk.sendStates[0]

    bridge.rebindEngineForTesting(engineB, viewControllerProvider: { UIViewController() })
    XCTAssertEqual(oldValues.count, 1)
    XCTAssertEqual(oldValues[0]["reason"] as? String, "ENGINE_DETACHED")

    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { _ in }
    )
    var newValues: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { newValues.append(value) } }
    )
    sdk.completeSend(true)
    let stateB = sdk.sendStates[1]
    bridge.handleProviderResponse(errorCode: 0, state: stateA, credential: "late-a")
    bridge.handleProviderResponse(errorCode: 0, state: stateB, credential: "credential-b")

    XCTAssertEqual(newValues.count, 1)
    XCTAssertEqual(newValues[0]["credential"] as? String, "credential-b")
  }

  func testURLRoutingRejectsUnrelatedAndDuplicateCallbacks() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = makeBridge(sdk: sdk, scheduler: ManualWechatIOSAuthScheduler())
    initializeWechatBridge(bridge)
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { _ in }
    )

    XCTAssertFalse(bridge.handleOpenURL(URL(string: "https://evil.example/callback")!))
    XCTAssertEqual(sdk.openURLCalls, 0)
    XCTAssertTrue(bridge.handleOpenURL(URL(string: "weixin://app/callback")!))
    XCTAssertEqual(sdk.openURLCalls, 1)
    let state = sdk.sendStates[0]
    bridge.handleProviderResponse(errorCode: 0, state: state, credential: "credential")
    XCTAssertFalse(bridge.handleOpenURL(URL(string: "weixin://app/duplicate")!))
    XCTAssertEqual(sdk.openURLCalls, 1)
  }

  func testUniversalLinkRoutingRequiresExpectedWebHostAndPath() {
    let sdk = FakeWechatIOSSDKClient()
    let bridge = makeBridge(sdk: sdk, scheduler: ManualWechatIOSAuthScheduler())
    initializeWechatBridge(bridge)
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { _ in }
    )

    let unrelated = NSUserActivity(activityType: NSUserActivityTypeBrowsingWeb)
    unrelated.webpageURL = URL(string: "https://evil.example/wechat/callback")
    XCTAssertFalse(bridge.handleOpenUniversalLink(unrelated))
    XCTAssertEqual(sdk.openUniversalLinkCalls, 0)

    let expected = NSUserActivity(activityType: NSUserActivityTypeBrowsingWeb)
    expected.webpageURL = URL(string: "https://example.invalid/wechat/callback")
    XCTAssertTrue(bridge.handleOpenUniversalLink(expected))
    XCTAssertEqual(sdk.openUniversalLinkCalls, 1)
  }

  func testTimeoutCompletesOnceRejectsLateCallbackAndCancelledTimerDoesNotFire() {
    let sdk = FakeWechatIOSSDKClient()
    let scheduler = ManualWechatIOSAuthScheduler()
    let bridge = makeBridge(sdk: sdk, scheduler: scheduler)
    initializeWechatBridge(bridge)
    var first: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { first.append(value) } }
    )
    let stateA = sdk.sendStates[0]
    scheduler.fireAll()
    bridge.handleProviderResponse(errorCode: 0, state: stateA, credential: "late-a")
    XCTAssertEqual(first.count, 1)
    XCTAssertEqual(first[0]["state"] as? String, "TIMEOUT")

    var second: [[String: Any]] = []
    bridge.handle(
      call: FlutterMethodCall(methodName: "requestCredential", arguments: nil),
      result: { if let value = $0 as? [String: Any] { second.append(value) } }
    )
    let stateB = sdk.sendStates[1]
    bridge.handle(
      call: FlutterMethodCall(methodName: "cancel", arguments: nil),
      result: { _ in }
    )
    scheduler.fireAll()
    bridge.handleProviderResponse(errorCode: 0, state: stateB, credential: "late-b")
    XCTAssertEqual(second.count, 1)
    XCTAssertEqual(second[0]["state"] as? String, "CANCELLED")
  }

  private func initializeWechatBridge(_ bridge: WechatAuthNativeBridge) {
    bridge.handle(
      call: FlutterMethodCall(
        methodName: "initialize",
        arguments: ["privacy_consent_granted": true]
      ),
      result: { _ in }
    )
  }
}
