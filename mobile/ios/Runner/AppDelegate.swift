import BackgroundTasks
import CoreLocation
import Flutter
import UIKit
import UserNotifications

enum PassiveMemoryBackgroundRecovery {
  static let identifier = "cn.jiyidashi.jiyidashi.passive-recovery"

  @available(iOS 13.0, *)
  static func schedule(
    earliest: Date = Date().addingTimeInterval(15 * 60)
  ) {
    BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: identifier)
    let request = BGAppRefreshTaskRequest(identifier: identifier)
    request.earliestBeginDate = earliest
    do {
      try BGTaskScheduler.shared.submit(request)
    } catch {
      // Scheduling is best-effort. Privacy remains fail-closed because CoreLocation
      // production is already stopped before this recovery request is submitted.
    }
  }

  @available(iOS 13.0, *)
  static func cancel() {
    BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: identifier)
  }
}

enum NativeLocationAuthorization {
  case notDetermined
  case foreground
  case background
  case denied
  case restricted
}

enum NativeLocationRuntime: String {
  case stopped
  case paused
  case running
}

struct NativeLocationRelaunchState: Equatable {
  let restorePending: Bool
  let runtime: NativeLocationRuntime
}


enum NativeMotionState: String, Codable {
  case unknown
  case stationary
  case walking
  case vehicle
}

struct NativeSamplingProfile: Equatable {
  let motionState: NativeMotionState
  let minIntervalMs: Int64
  let minDistanceMeters: Double
  let maxAccuracyMeters: Double

  static let fallback = NativeSamplingProfile(
    motionState: .unknown,
    minIntervalMs: 120_000,
    minDistanceMeters: 75,
    maxAccuracyMeters: 120
  )

  static func validated(
    motionState: NativeMotionState,
    minIntervalMs: Int64,
    minDistanceMeters: Double,
    maxAccuracyMeters: Double
  ) -> NativeSamplingProfile? {
    guard
      minIntervalMs >= 15_000,
      minDistanceMeters.isFinite,
      minDistanceMeters >= 5,
      maxAccuracyMeters.isFinite,
      maxAccuracyMeters >= 10
    else {
      return nil
    }
    return NativeSamplingProfile(
      motionState: motionState,
      minIntervalMs: minIntervalMs,
      minDistanceMeters: minDistanceMeters,
      maxAccuracyMeters: maxAccuracyMeters
    )
  }
}

struct NativeQueuedLocationSample: Codable {
  let ownerUserId: String
  let clientUuid: String
  let latitude: Double
  let longitude: Double
  let accuracyMeters: Double?
  let speedMetersPerSecond: Double?
  let recordedAtMillis: Int64
  let queueSequence: Int64
  let enqueuedAtMillis: Int64
  let handoffAttemptCount: Int

  init(
    ownerUserId: String,
    clientUuid: String,
    latitude: Double,
    longitude: Double,
    accuracyMeters: Double?,
    speedMetersPerSecond: Double?,
    recordedAtMillis: Int64,
    queueSequence: Int64 = 0,
    enqueuedAtMillis: Int64? = nil,
    handoffAttemptCount: Int = 0
  ) {
    self.ownerUserId = ownerUserId
    self.clientUuid = clientUuid
    self.latitude = latitude
    self.longitude = longitude
    self.accuracyMeters = accuracyMeters
    self.speedMetersPerSecond = speedMetersPerSecond
    self.recordedAtMillis = recordedAtMillis
    self.queueSequence = queueSequence
    self.enqueuedAtMillis = enqueuedAtMillis ?? recordedAtMillis
    self.handoffAttemptCount = max(handoffAttemptCount, 0)
  }

  private enum CodingKeys: String, CodingKey {
    case ownerUserId
    case clientUuid
    case latitude
    case longitude
    case accuracyMeters
    case speedMetersPerSecond
    case recordedAtMillis
    case queueSequence
    case enqueuedAtMillis
    case handoffAttemptCount
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    let recordedAt = try container.decode(Int64.self, forKey: .recordedAtMillis)
    self.init(
      ownerUserId: try container.decode(String.self, forKey: .ownerUserId),
      clientUuid: try container.decode(String.self, forKey: .clientUuid),
      latitude: try container.decode(Double.self, forKey: .latitude),
      longitude: try container.decode(Double.self, forKey: .longitude),
      accuracyMeters: try container.decodeIfPresent(Double.self, forKey: .accuracyMeters),
      speedMetersPerSecond:
        try container.decodeIfPresent(Double.self, forKey: .speedMetersPerSecond),
      recordedAtMillis: recordedAt,
      queueSequence: try container.decodeIfPresent(Int64.self, forKey: .queueSequence) ?? 0,
      enqueuedAtMillis:
        try container.decodeIfPresent(Int64.self, forKey: .enqueuedAtMillis) ?? recordedAt,
      handoffAttemptCount:
        try container.decodeIfPresent(Int.self, forKey: .handoffAttemptCount) ?? 0
    )
  }
}

struct NativeMotionObservation: Codable {
  let ownerUserId: String
  let accuracyMeters: Double?
  let speedMetersPerSecond: Double?
  let recordedAtMillis: Int64
}

struct NativeOwnerQueueQuota {
  static func hasCapacity(
    samples: [NativeQueuedLocationSample],
    ownerUserId: String,
    maxPerOwner: Int
  ) -> Bool {
    guard maxPerOwner > 0 else { return false }
    // [人工注释][S2-004/005] Capacity is isolated by authenticated owner.
    return samples.filter { $0.ownerUserId == ownerUserId }.count < maxPerOwner
  }
}

/// Pure platform-signal mapping keeps iOS's negative "unavailable" values out of Dart.
struct NativeMotionSignalMapper {
  static func normalizedSpeed(_ speed: CLLocationSpeed) -> Double? {
    guard speed.isFinite, speed >= 0 else { return nil }
    return speed
  }

  static func normalizedAccuracy(_ accuracy: CLLocationAccuracy) -> Double? {
    guard accuracy.isFinite, accuracy >= 0 else { return nil }
    return accuracy
  }
}

struct NativeLocationSampleAdmission {
  static func accepts(
    accuracyMeters: Double?,
    profile: NativeSamplingProfile
  ) -> Bool {
    accuracyMeters == nil || accuracyMeters! <= profile.maxAccuracyMeters
  }

  static func cadenceAllows(
    previousRecordedAtMillis: Int64?,
    candidateRecordedAtMillis: Int64,
    minIntervalMs: Int64
  ) -> Bool {
    guard let previousRecordedAtMillis else { return true }
    return candidateRecordedAtMillis - previousRecordedAtMillis >= minIntervalMs
  }
}

/// Pure permission/runtime policy kept free of CLLocationManager side effects so the
/// privacy invariants can be exercised directly by RunnerTests.
struct NativeLocationPolicy {
  static func recordingHealthBackgroundRuntime(
    authorization: NativeLocationAuthorization,
    locationServicesEnabled: Bool
  ) -> String {
    guard authorization == .background && locationServicesEnabled else {
      return "unknown"
    }
    return "eligible"
  }

  static func canStart(
    ownerUserId: String,
    enabledOwnerUserId: String?,
    authorization: NativeLocationAuthorization,
    locationServicesEnabled: Bool
  ) -> Bool {
    !ownerUserId.isEmpty &&
      ownerUserId == enabledOwnerUserId &&
      authorization == .background &&
      locationServicesEnabled
  }

  static func shouldRequestAlways(
    explicitAutomaticEnable: Bool,
    authorization: NativeLocationAuthorization
  ) -> Bool {
    explicitAutomaticEnable && authorization == .foreground
  }

  static func relaunchState(
    enabledOwnerUserId: String?,
    activeOwnerUserId: String?,
    authorization: NativeLocationAuthorization,
    locationServicesEnabled: Bool,
    runtime: NativeLocationRuntime
  ) -> NativeLocationRelaunchState {
    guard
      let enabledOwnerUserId,
      !enabledOwnerUserId.isEmpty,
      enabledOwnerUserId == activeOwnerUserId,
      authorization == .background,
      locationServicesEnabled,
      runtime == .running
    else {
      return NativeLocationRelaunchState(
        restorePending: false,
        runtime: .stopped
      )
    }
    // A location relaunch proves only that the old native producer was eligible to resume.
    // Server privacy is not known yet. PAUSED is the truthful product/runtime state here:
    // every CLLocation producer is stopped, while explicit enable consent and recovery intent
    // remain durable until Flutter verifies fresh AUTH + Privacy authority.
    return NativeLocationRelaunchState(
      restorePending: true,
      runtime: .paused
    )
  }

  static func reconcileRuntime(
    ownerUserId: String,
    enabledOwnerUserId: String?,
    authorization: NativeLocationAuthorization,
    locationServicesEnabled: Bool,
    runtime: NativeLocationRuntime,
    nativeProducerActive: Bool
  ) -> NativeLocationRuntime {
    guard runtime == .running else { return runtime }
    guard nativeProducerActive else { return .stopped }
    return canStart(
      ownerUserId: ownerUserId,
      enabledOwnerUserId: enabledOwnerUserId,
      authorization: authorization,
      locationServicesEnabled: locationServicesEnabled
    ) ? .running : .stopped
  }
}

final class NativeLocationBridge: NSObject, CLLocationManagerDelegate {
  private let manager = CLLocationManager()
  private let defaults = UserDefaults.standard
  private lazy var queueFileURL: URL? = {
    let manager = FileManager.default
    guard let base = manager.urls(
      for: .applicationSupportDirectory,
      in: .userDomainMask
    ).first else {
      return nil
    }
    do {
      try manager.createDirectory(
        at: base,
        withIntermediateDirectories: true
      )
      return base.appendingPathComponent(
        "native_location_queue_v2.json",
        isDirectory: false
      )
    } catch {
      return nil
    }
  }()
  private var channel: FlutterMethodChannel?
  private var passiveRecoveryListenerReady = false
  var onPassiveRecoveryReady: (() -> Void)?
  private var queueStorageUnavailable = false
  private var nativeProducerActive = false
  private var standardUpdatesActive = false

  override init() {
    super.init()
    manager.delegate = self
    manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    manager.distanceFilter = 50
    manager.pausesLocationUpdatesAutomatically = true
  }

  func attach(messenger: FlutterBinaryMessenger) {
    channel?.setMethodCallHandler(nil)
    passiveRecoveryListenerReady = false
    let nextChannel = FlutterMethodChannel(
      name: "cn.jiyidashi/native_location",
      binaryMessenger: messenger
    )
    nextChannel.setMethodCallHandler { [weak self] call, result in
      self?.handle(call: call, result: result)
    }
    channel = nextChannel
  }

  func sealAutomaticProductionForAuthorityLoss() {
    guard let owner = enabledOwnerUserId ?? activeOwnerUserId else { return }
    // Server/session authority loss is a quarantine, not an implicit user preference change.
    // pause() stops every CoreLocation producer while retaining enabledOwnerUserId and a
    // restore hint for a later fresh AUTH + Privacy verification.
    _ = pause(ownerUserId: owner)
  }

  func disableAutomaticProductionForAccountDeletion() {
    guard let owner = enabledOwnerUserId ?? activeOwnerUserId else { return }
    _ = disableAutomaticLocation(ownerUserId: owner)
  }

  @discardableResult
  func requestPassiveRecoveryWakeup() -> Bool {
    guard passiveRecoveryListenerReady, let channel else { return false }
    channel.invokeMethod("passiveRecoveryRequested", arguments: nil)
    return true
  }

  func markLocationRelaunchRestorePending() {
    let next = NativeLocationPolicy.relaunchState(
      enabledOwnerUserId: enabledOwnerUserId,
      activeOwnerUserId: activeOwnerUserId,
      authorization: authorization(),
      locationServicesEnabled: CLLocationManager.locationServicesEnabled(),
      runtime: runtime
    )

    // CoreLocation may relaunch the process before Flutter/auth/server privacy are available.
    // Never restart the producer here. Persist only a recovery hint and force truthful stopped
    // runtime; Flutter may later consume the hint after authoritative privacy verification.
    manager.stopMonitoringSignificantLocationChanges()
    manager.stopUpdatingLocation()
    standardUpdatesActive = false
    if let activeOwnerUserId {
      finishTracking(ownerUserId: activeOwnerUserId)
    }
    manager.allowsBackgroundLocationUpdates = false
    nativeProducerActive = false
    relaunchRestorePending = next.restorePending
    runtime = next.runtime
    if !next.restorePending {
      activeOwnerUserId = nil
    }
  }

  private func handle(call: FlutterMethodCall, result: @escaping FlutterResult) {
    if call.method == "awaitPassiveRecoveryIdle" {
      // iOS uses the single implicit Flutter engine for CoreLocation relaunch recovery.
      // Keep the cross-platform startup seam explicit while returning immediately here.
      result(true)
      return
    }
    if call.method == "passiveRecoveryReady" {
      passiveRecoveryListenerReady = true
      onPassiveRecoveryReady?()
      result(true)
      return
    }

    guard let ownerUserId = owner(from: call) else {
      result(FlutterError(
        code: "invalid_owner",
        message: "Authenticated user id is required",
        details: nil
      ))
      return
    }

    switch call.method {
    case "status":
      result(status(ownerUserId: ownerUserId))
    case "requestForegroundPermission":
      result(requestForegroundPermission(ownerUserId: ownerUserId))
    case "enableAutomaticLocation":
      result(enableAutomaticLocation(ownerUserId: ownerUserId))
    case "openBackgroundLocationSettings":
      // Android 11+ uses this cross-platform bridge method. iOS Always permission has its
      // own explicit CoreLocation flow, so this is intentionally status-only here.
      result(status(ownerUserId: ownerUserId))
    case "openLocationServicesSettings":
      if let settingsURL = URL(string: UIApplication.openSettingsURLString) {
        UIApplication.shared.open(settingsURL, options: [:], completionHandler: nil)
      }
      result(status(ownerUserId: ownerUserId))
    case "disableAutomaticLocation":
      result(disableAutomaticLocation(ownerUserId: ownerUserId))
    case "start":
      result(start(ownerUserId: ownerUserId))
    case "pause":
      result(pause(ownerUserId: ownerUserId))
    case "stop":
      result(stop(ownerUserId: ownerUserId))
    case "drainLocationSamples":
      result(drainLocationSamples(call: call, ownerUserId: ownerUserId))
    case "takeMotionObservation":
      result(takeMotionObservation(ownerUserId: ownerUserId))
    case "ackLocationSamples":
      acknowledgeLocationSamples(call: call, ownerUserId: ownerUserId)
      result(nil)
    case "applySamplingProfile":
      applySamplingProfile(call: call, ownerUserId: ownerUserId, result: result)
    case "locationMetrics":
      result(locationMetrics(ownerUserId: ownerUserId))
    case "recordLocationUploadBatch":
      if
        let arguments = call.arguments as? [String: Any],
        let count = arguments["sample_count"] as? NSNumber,
        count.intValue > 0
      {
        incrementMetric(
          ownerUserId: ownerUserId,
          prefix: Keys.metricUploadBatches,
          delta: 1
        )
        incrementMetric(
          ownerUserId: ownerUserId,
          prefix: Keys.metricUploadedSamples,
          delta: Int64(count.intValue)
        )
        defaults.set(
          Int64(Date().timeIntervalSince1970 * 1000),
          forKey: ownerKey(Keys.lastDeliveryAt, ownerUserId)
        )
        if #available(iOS 13.0, *) {
          let remaining =
            allPendingLocationSamples().contains { $0.ownerUserId == ownerUserId }
          if queueStorageUnavailable || remaining {
            PassiveMemoryBackgroundRecovery.schedule()
          } else {
            PassiveMemoryBackgroundRecovery.cancel()
          }
        }
      }
      result(nil)
    case "recordLocationDeliveryFailure":
      let arguments = call.arguments as? [String: Any]
      let reason =
        (arguments?["reason"] as? String)?
          .trimmingCharacters(in: .whitespacesAndNewlines)
      incrementMetric(
        ownerUserId: ownerUserId,
        prefix: Keys.deliveryFailureCount,
        delta: 1
      )
      defaults.set(
        Int64(Date().timeIntervalSince1970 * 1000),
        forKey: ownerKey(Keys.lastDeliveryFailureAt, ownerUserId)
      )
      defaults.set(
        (reason?.isEmpty == false ? reason! : "location_delivery_failed"),
        forKey: ownerKey(Keys.lastDeliveryFailureReason, ownerUserId)
      )
      result(nil)
    case "recordLocationLifecycleDiagnostic":
      let arguments = call.arguments as? [String: Any]
      let event =
        (arguments?["event"] as? String)?
          .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
      let reason =
        (arguments?["reason"] as? String)?
          .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
      guard
        ["pause", "recovery_attempt", "recovery_result", "disable"].contains(event),
        !reason.isEmpty
      else {
        result(FlutterError(
          code: "invalid_lifecycle_diagnostic",
          message: "Lifecycle diagnostic event/reason is invalid",
          details: nil
        ))
        return
      }
      recordLifecycleDiagnostic(
        ownerUserId: ownerUserId,
        event: event,
        reason: reason,
        result:
          (arguments?["result"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
        success: arguments?["success"] as? Bool
      )
      result(nil)
    case "purgeLocationSamplingOwner":
      purgeLocationSamplingOwner(ownerUserId)
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func owner(from call: FlutterMethodCall) -> String? {
    guard
      let arguments = call.arguments as? [String: Any],
      let raw = arguments["owner_user_id"] as? String
    else {
      return nil
    }
    let owner = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    return owner.isEmpty ? nil : owner
  }

  private var enabledOwnerUserId: String? {
    get { defaults.string(forKey: Keys.enabledOwnerUserId) }
    set { defaults.set(newValue, forKey: Keys.enabledOwnerUserId) }
  }

  private var activeOwnerUserId: String? {
    get { defaults.string(forKey: Keys.activeOwnerUserId) }
    set { defaults.set(newValue, forKey: Keys.activeOwnerUserId) }
  }

  private var pendingEnableOwnerUserId: String? {
    get { defaults.string(forKey: Keys.pendingEnableOwnerUserId) }
    set { defaults.set(newValue, forKey: Keys.pendingEnableOwnerUserId) }
  }

  private var relaunchRestorePending: Bool {
    get { defaults.bool(forKey: Keys.relaunchRestorePending) }
    set { defaults.set(newValue, forKey: Keys.relaunchRestorePending) }
  }

  private var runtime: NativeLocationRuntime {
    get {
      NativeLocationRuntime(
        rawValue: defaults.string(forKey: Keys.runtime) ?? ""
      ) ?? .stopped
    }
    set {
      defaults.set(newValue.rawValue, forKey: Keys.runtime)
    }
  }

  private func samplingProfile(ownerUserId: String) -> NativeSamplingProfile {
    guard
      let data = defaults.data(forKey: ownerKey(Keys.samplingProfile, ownerUserId)),
      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
      let rawState = object["motion_state"] as? String,
      let state = NativeMotionState(rawValue: rawState),
      let interval = (object["min_interval_ms"] as? NSNumber)?.int64Value,
      let distance = (object["min_distance_m"] as? NSNumber)?.doubleValue,
      let maxAccuracy = (object["max_accuracy_m"] as? NSNumber)?.doubleValue,
      let profile = NativeSamplingProfile.validated(
        motionState: state,
        minIntervalMs: interval,
        minDistanceMeters: distance,
        maxAccuracyMeters: maxAccuracy
      )
    else {
      return .fallback
    }
    return profile
  }

  private func setSamplingProfile(
    ownerUserId: String,
    profile: NativeSamplingProfile
  ) {
    let object: [String: Any] = [
      "motion_state": profile.motionState.rawValue,
      "min_interval_ms": profile.minIntervalMs,
      "min_distance_m": profile.minDistanceMeters,
      "max_accuracy_m": profile.maxAccuracyMeters,
    ]
    if let data = try? JSONSerialization.data(withJSONObject: object) {
      defaults.set(data, forKey: ownerKey(Keys.samplingProfile, ownerUserId))
    }
  }

  private func configureSamplingProfile(ownerUserId: String) {
    let profile = samplingProfile(ownerUserId: ownerUserId)
    manager.distanceFilter = profile.minDistanceMeters
    switch profile.motionState {
    case .stationary:
      manager.desiredAccuracy = kCLLocationAccuracyKilometer
      if standardUpdatesActive {
        manager.stopUpdatingLocation()
        standardUpdatesActive = false
      }
    case .walking:
      manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
      if !standardUpdatesActive {
        manager.startUpdatingLocation()
        standardUpdatesActive = true
      }
    case .vehicle:
      manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
      if !standardUpdatesActive {
        manager.startUpdatingLocation()
        standardUpdatesActive = true
      }
    case .unknown:
      manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
      if !standardUpdatesActive {
        manager.startUpdatingLocation()
        standardUpdatesActive = true
      }
    }
  }

  private func drainLocationSamples(
    call: FlutterMethodCall,
    ownerUserId: String
  ) -> [[String: Any]] {
    let arguments = call.arguments as? [String: Any]
    let limit = min(max((arguments?["limit"] as? NSNumber)?.intValue ?? 100, 1), 500)
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return pendingLocationSamples(ownerUserId: ownerUserId, limit: limit)
      .map { sample in
        var payload: [String: Any] = [
          "client_uuid": sample.clientUuid,
          "latitude": sample.latitude,
          "longitude": sample.longitude,
          "recorded_at": formatter.string(
            from: Date(timeIntervalSince1970: Double(sample.recordedAtMillis) / 1000.0)
          ),
        ]
        payload["accuracy"] = sample.accuracyMeters ?? NSNull()
        payload["speed"] = sample.speedMetersPerSecond ?? NSNull()
        return payload
      }
  }

  private func takeMotionObservation(ownerUserId: String) -> [String: Any]? {
    let key = ownerKey(Keys.latestMotionObservation, ownerUserId)
    guard
      let data = defaults.data(forKey: key),
      let observation = try? JSONDecoder().decode(
        NativeMotionObservation.self,
        from: data
      ),
      observation.ownerUserId == ownerUserId
    else {
      defaults.removeObject(forKey: key)
      return nil
    }
    defaults.removeObject(forKey: key)
    return [
      "accuracy": observation.accuracyMeters ?? NSNull(),
      "speed": observation.speedMetersPerSecond ?? NSNull(),
      "recorded_at_millis": observation.recordedAtMillis,
    ]
  }

  private func acknowledgeLocationSamples(
    call: FlutterMethodCall,
    ownerUserId: String
  ) {
    guard
      let arguments = call.arguments as? [String: Any],
      let ids = arguments["client_uuids"] as? [String]
    else {
      return
    }
    let normalized = Set(ids.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) })
    let retained = allPendingLocationSamples().filter {
      !($0.ownerUserId == ownerUserId && normalized.contains($0.clientUuid))
    }
    if !queueCorrupt && !savePendingLocationSamples(retained) {
      markQueueCorrupt("native_queue_persist_failed")
    }
  }

  private func applySamplingProfile(
    call: FlutterMethodCall,
    ownerUserId: String,
    result: @escaping FlutterResult
  ) {
    guard enabledOwnerUserId == ownerUserId else {
      result(FlutterError(
        code: "owner_mismatch",
        message: "Automatic location owner does not match",
        details: nil
      ))
      return
    }
    guard
      let arguments = call.arguments as? [String: Any],
      let rawState = arguments["motion_state"] as? String,
      let state = NativeMotionState(rawValue: rawState),
      let interval = (arguments["min_interval_ms"] as? NSNumber)?.int64Value,
      let distance = (arguments["min_distance_m"] as? NSNumber)?.doubleValue,
      let maxAccuracy = (arguments["max_accuracy_m"] as? NSNumber)?.doubleValue,
      let profile = NativeSamplingProfile.validated(
        motionState: state,
        minIntervalMs: interval,
        minDistanceMeters: distance,
        maxAccuracyMeters: maxAccuracy
      )
    else {
      result(FlutterError(
        code: "invalid_sampling_profile",
        message: "Sampling profile is invalid",
        details: nil
      ))
      return
    }
    setSamplingProfile(ownerUserId: ownerUserId, profile: profile)
    if runtime == .running && activeOwnerUserId == ownerUserId {
      // Reconfigure the existing authorized producer only; this never requests permission.
      configureSamplingProfile(ownerUserId: ownerUserId)
    }
    result(nil)
  }

  private func ownerKey(_ prefix: String, _ ownerUserId: String) -> String {
    "\(prefix).\(ownerUserId)"
  }

  private var queueCorrupt: Bool {
    defaults.bool(forKey: Keys.queueCorrupt)
  }

  private func markQueueCorrupt(_ reason: String) {
    defaults.set(true, forKey: Keys.queueCorrupt)
    defaults.set(reason, forKey: Keys.queueCorruptReason)
    defaults.set(
      Int64(Date().timeIntervalSince1970 * 1000),
      forKey: Keys.queueCorruptAt
    )
  }

  private func allPendingLocationSamples() -> [NativeQueuedLocationSample] {
    if queueCorrupt { return [] }
    queueStorageUnavailable = false

    var cameFromLegacyDefaults = false
    let data: Data
    if let url = queueFileURL,
       FileManager.default.fileExists(atPath: url.path) {
      do {
        data = try Data(contentsOf: url)
      } catch {
        // File protection / transient I/O unavailability is not corruption. Keep the
        // existing file untouched and refuse drain/enqueue until a later read succeeds.
        queueStorageUnavailable = true
        return []
      }
    } else if let legacy = defaults.data(forKey: Keys.pendingSamples) {
      data = legacy
      cameFromLegacyDefaults = true
    } else {
      return []
    }

    guard var samples = try? JSONDecoder().decode(
      [NativeQueuedLocationSample].self,
      from: data
    ) else {
      // Preserve the original durable payload. Never reinterpret corruption as an empty
      // queue and overwrite precise-location evidence on the next enqueue.
      markQueueCorrupt("native_queue_decode_failed")
      return []
    }
    guard samples.allSatisfy({
      !$0.ownerUserId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        !$0.clientUuid.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        $0.latitude.isFinite && (-90...90).contains($0.latitude) &&
        $0.longitude.isFinite && (-180...180).contains($0.longitude)
    }) else {
      markQueueCorrupt("native_queue_validation_failed")
      return []
    }

    let schema = defaults.integer(forKey: Keys.queueSchemaVersion)
    if cameFromLegacyDefaults ||
        schema < 2 ||
        samples.contains(where: { $0.queueSequence <= 0 }) {
      var next: Int64 = 1
      samples = samples.map { sample in
        let sequence = sample.queueSequence > 0 ? sample.queueSequence : next
        next = max(next, sequence + 1)
        return NativeQueuedLocationSample(
          ownerUserId: sample.ownerUserId,
          clientUuid: sample.clientUuid,
          latitude: sample.latitude,
          longitude: sample.longitude,
          accuracyMeters: sample.accuracyMeters,
          speedMetersPerSecond: sample.speedMetersPerSecond,
          recordedAtMillis: sample.recordedAtMillis,
          queueSequence: sequence,
          enqueuedAtMillis:
            sample.enqueuedAtMillis > 0 ? sample.enqueuedAtMillis : sample.recordedAtMillis,
          handoffAttemptCount: sample.handoffAttemptCount
        )
      }
      guard savePendingLocationSamples(samples) else {
        markQueueCorrupt("native_queue_migration_persist_failed")
        return []
      }
      defaults.set(2, forKey: Keys.queueSchemaVersion)
      defaults.set(next, forKey: Keys.nextQueueSequence)
      if cameFromLegacyDefaults {
        // Delete the legacy blob only after the V2 atomic file is durable.
        defaults.removeObject(forKey: Keys.pendingSamples)
      }
    }
    return samples
  }

  @discardableResult
  private func savePendingLocationSamples(
    _ samples: [NativeQueuedLocationSample]
  ) -> Bool {
    guard
      let url = queueFileURL,
      let data = try? JSONEncoder().encode(samples)
    else {
      return false
    }
    do {
      // Atomic replace gives crash-safe file-level durability without requiring CoreData
      // or a second SQLite authority beside the Flutter outbox.
      try data.write(
        to: url,
        options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
      )
      defaults.set(2, forKey: Keys.queueSchemaVersion)
      return true
    } catch {
      return false
    }
  }

  private func pendingLocationSamples(
    ownerUserId: String,
    limit: Int
  ) -> [NativeQueuedLocationSample] {
    let samples = allPendingLocationSamples()
    if queueCorrupt || queueStorageUnavailable { return [] }
    let selectedSequences = Set(
      samples
        .filter { $0.ownerUserId == ownerUserId }
        .prefix(min(max(limit, 1), 500))
        .map { $0.queueSequence }
    )
    if selectedSequences.isEmpty { return [] }
    let updated = samples.map { sample -> NativeQueuedLocationSample in
      guard selectedSequences.contains(sample.queueSequence) else { return sample }
      return NativeQueuedLocationSample(
        ownerUserId: sample.ownerUserId,
        clientUuid: sample.clientUuid,
        latitude: sample.latitude,
        longitude: sample.longitude,
        accuracyMeters: sample.accuracyMeters,
        speedMetersPerSecond: sample.speedMetersPerSecond,
        recordedAtMillis: sample.recordedAtMillis,
        queueSequence: sample.queueSequence,
        enqueuedAtMillis: sample.enqueuedAtMillis,
        handoffAttemptCount: sample.handoffAttemptCount + 1
      )
    }
    guard savePendingLocationSamples(updated) else {
      markQueueCorrupt("native_queue_persist_failed")
      return []
    }
    return updated.filter { selectedSequences.contains($0.queueSequence) }
  }

  private func enqueueLocationSample(
    _ sample: NativeQueuedLocationSample
  ) -> Bool {
    var samples = allPendingLocationSamples()
    if queueCorrupt || queueStorageUnavailable { return false }
    if samples.contains(where: {
      $0.ownerUserId == sample.ownerUserId &&
        $0.clientUuid == sample.clientUuid
    }) {
      return true
    }
    let ownerQueueWasEmpty =
      !samples.contains(where: { $0.ownerUserId == sample.ownerUserId })
    guard NativeOwnerQueueQuota.hasCapacity(
      samples: samples,
      ownerUserId: sample.ownerUserId,
      maxPerOwner: 1000
    ) else {
      recordCapacityDrop(ownerUserId: sample.ownerUserId, reason: "native_queue_capacity")
      return false
    }
    let next = max(
      1,
      max(
        Int64(defaults.integer(forKey: Keys.nextQueueSequence)),
        (samples.map { $0.queueSequence }.max() ?? 0) + 1
      )
    )
    let now = Int64(Date().timeIntervalSince1970 * 1000)
    let persisted = NativeQueuedLocationSample(
      ownerUserId: sample.ownerUserId,
      clientUuid: sample.clientUuid,
      latitude: sample.latitude,
      longitude: sample.longitude,
      accuracyMeters: sample.accuracyMeters,
      speedMetersPerSecond: sample.speedMetersPerSecond,
      recordedAtMillis: sample.recordedAtMillis,
      queueSequence: next,
      enqueuedAtMillis: now,
      handoffAttemptCount: 0
    )
    samples.append(persisted)
    guard savePendingLocationSamples(samples) else {
      markQueueCorrupt("native_queue_persist_failed")
      return false
    }
    defaults.set(next + 1, forKey: Keys.nextQueueSequence)
    defaults.set(now, forKey: ownerKey(Keys.lastEnqueueAt, sample.ownerUserId))
    if ownerQueueWasEmpty, #available(iOS 13.0, *) {
      // A first durable native sample creates a recovery obligation even if the app is
      // suspended/killed before Dart receives samplesAvailable.
      PassiveMemoryBackgroundRecovery.schedule()
    }
    return true
  }

  private func setLatestMotionObservation(
    _ observation: NativeMotionObservation
  ) {
    // [人工注释][S2-004/005] This advisory signal contains no coordinates; it can
    // survive the raw quality gate and drive backoff without retaining a rejected fix.
    if let data = try? JSONEncoder().encode(observation) {
      defaults.set(
        data,
        forKey: ownerKey(Keys.latestMotionObservation, observation.ownerUserId)
      )
    }
  }

  private func purgeLocationSamplingOwner(_ ownerUserId: String) {
    if activeOwnerUserId == ownerUserId {
      stopProduction(runtimeAfterStop: .stopped)
    }
    if queueCorrupt {
      // Account deletion is privacy-authoritative. A corrupt mixed-owner payload
      // cannot be filtered safely, so erase the complete raw queue rather than retain
      // precise locations for the owner being deleted.
      if let url = queueFileURL {
        try? FileManager.default.removeItem(at: url)
      }
      defaults.removeObject(forKey: Keys.pendingSamples)
      defaults.removeObject(forKey: Keys.queueCorrupt)
      defaults.removeObject(forKey: Keys.queueCorruptReason)
      defaults.removeObject(forKey: Keys.queueCorruptAt)
      defaults.set(2, forKey: Keys.queueSchemaVersion)
    } else {
      _ = savePendingLocationSamples(
        allPendingLocationSamples().filter { $0.ownerUserId != ownerUserId }
      )
    }
    let prefixes = [
      Keys.samplingProfile,
      Keys.latestMotionObservation,
      Keys.metricWakeups,
      Keys.metricAccepted,
      Keys.metricDropped,
      Keys.metricUploadBatches,
      Keys.metricUploadedSamples,
      Keys.metricActiveMs,
      Keys.trackingStartedAt,
      Keys.lastQueuedAt,
      Keys.lastEnqueueAt,
      Keys.lastDeliveryAt,
      Keys.deliveryFailureCount,
      Keys.lastDeliveryFailureAt,
      Keys.lastDeliveryFailureReason,
      Keys.capacityDropCount,
      Keys.lastDropAt,
      Keys.lastDropReason,
      Keys.lifecyclePauseCount,
      Keys.lifecycleLastPauseAt,
      Keys.lifecycleLastPauseReason,
      Keys.lifecycleRecoveryAttemptCount,
      Keys.lifecycleLastRecoveryAt,
      Keys.lifecycleLastRecoveryReason,
      Keys.lifecycleLastRecoveryResult,
      Keys.lifecycleLastRecoverySuccessAt,
      Keys.lifecycleDisableCount,
      Keys.lifecycleLastDisableAt,
      Keys.lifecycleLastDisableReason,
    ]
    for prefix in prefixes {
      defaults.removeObject(forKey: ownerKey(prefix, ownerUserId))
    }
  }

  private func recordCapacityDrop(
    ownerUserId: String,
    reason: String,
    nowMillis: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
  ) {
    incrementMetric(
      ownerUserId: ownerUserId,
      prefix: Keys.capacityDropCount,
      delta: 1
    )
    defaults.set(nowMillis, forKey: ownerKey(Keys.lastDropAt, ownerUserId))
    defaults.set(reason, forKey: ownerKey(Keys.lastDropReason, ownerUserId))
  }

  private func recordLifecycleDiagnostic(
    ownerUserId: String,
    event: String,
    reason: String,
    result: String? = nil,
    success: Bool? = nil,
    nowMillis: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
  ) {
    let normalizedReason =
      reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        ? "unknown"
        : reason.trimmingCharacters(in: .whitespacesAndNewlines)
    switch event {
    case "pause":
      incrementMetric(ownerUserId: ownerUserId, prefix: Keys.lifecyclePauseCount, delta: 1)
      defaults.set(nowMillis, forKey: ownerKey(Keys.lifecycleLastPauseAt, ownerUserId))
      defaults.set(
        normalizedReason,
        forKey: ownerKey(Keys.lifecycleLastPauseReason, ownerUserId)
      )
    case "recovery_attempt":
      incrementMetric(
        ownerUserId: ownerUserId,
        prefix: Keys.lifecycleRecoveryAttemptCount,
        delta: 1
      )
      defaults.set(nowMillis, forKey: ownerKey(Keys.lifecycleLastRecoveryAt, ownerUserId))
      defaults.set(
        normalizedReason,
        forKey: ownerKey(Keys.lifecycleLastRecoveryReason, ownerUserId)
      )
    case "recovery_result":
      defaults.set(nowMillis, forKey: ownerKey(Keys.lifecycleLastRecoveryAt, ownerUserId))
      defaults.set(
        normalizedReason,
        forKey: ownerKey(Keys.lifecycleLastRecoveryReason, ownerUserId)
      )
      defaults.set(
        (result?.isEmpty == false ? result! : "unknown"),
        forKey: ownerKey(Keys.lifecycleLastRecoveryResult, ownerUserId)
      )
      if success == true {
        defaults.set(
          nowMillis,
          forKey: ownerKey(Keys.lifecycleLastRecoverySuccessAt, ownerUserId)
        )
      }
    case "disable":
      incrementMetric(ownerUserId: ownerUserId, prefix: Keys.lifecycleDisableCount, delta: 1)
      defaults.set(nowMillis, forKey: ownerKey(Keys.lifecycleLastDisableAt, ownerUserId))
      defaults.set(
        normalizedReason,
        forKey: ownerKey(Keys.lifecycleLastDisableReason, ownerUserId)
      )
    default:
      return
    }
  }

  private func lifecycleDiagnostics(ownerUserId: String) -> [String: Any] {
    func millis(_ key: String) -> Any {
      let scoped = ownerKey(key, ownerUserId)
      return defaults.object(forKey: scoped) == nil
        ? NSNull()
        : Int64(defaults.integer(forKey: scoped))
    }
    func text(_ key: String) -> Any {
      defaults.string(forKey: ownerKey(key, ownerUserId)).map { $0 as Any }
        ?? NSNull()
    }
    return [
      "pause_count":
        Int64(defaults.integer(forKey: ownerKey(Keys.lifecyclePauseCount, ownerUserId))),
      "last_pause_at_millis": millis(Keys.lifecycleLastPauseAt),
      "last_pause_reason": text(Keys.lifecycleLastPauseReason),
      "recovery_attempt_count":
        Int64(
          defaults.integer(
            forKey: ownerKey(Keys.lifecycleRecoveryAttemptCount, ownerUserId)
          )
        ),
      "last_recovery_at_millis": millis(Keys.lifecycleLastRecoveryAt),
      "last_recovery_reason": text(Keys.lifecycleLastRecoveryReason),
      "last_recovery_result": text(Keys.lifecycleLastRecoveryResult),
      "last_recovery_success_at_millis": millis(Keys.lifecycleLastRecoverySuccessAt),
      "disable_count":
        Int64(defaults.integer(forKey: ownerKey(Keys.lifecycleDisableCount, ownerUserId))),
      "last_disable_at_millis": millis(Keys.lifecycleLastDisableAt),
      "last_disable_reason": text(Keys.lifecycleLastDisableReason),
    ]
  }

  private func queueDiagnostics(ownerUserId: String) -> [String: Any] {
    let samples = allPendingLocationSamples().filter { $0.ownerUserId == ownerUserId }
    let depth = samples.count
    func millis(_ key: String) -> Any {
      let scoped = ownerKey(key, ownerUserId)
      return defaults.object(forKey: scoped) == nil
        ? NSNull()
        : Int64(defaults.integer(forKey: scoped))
    }
    func text(_ key: String) -> Any {
      defaults.string(forKey: ownerKey(key, ownerUserId)).map { $0 as Any }
        ?? NSNull()
    }
    let oldest: Any =
      samples.map { $0.enqueuedAtMillis }.min().map { $0 as Any } ?? NSNull()
    let corruptReason: Any =
      defaults.string(forKey: Keys.queueCorruptReason).map { $0 as Any } ?? NSNull()
    return [
      "queue_schema_version": 2,
      "queue_depth": depth,
      "queue_capacity": 1000,
      "oldest_pending_at_millis": oldest,
      "last_enqueue_at_millis": millis(Keys.lastEnqueueAt),
      "last_delivery_at_millis": millis(Keys.lastDeliveryAt),
      "delivery_failure_count":
        Int64(defaults.integer(forKey: ownerKey(Keys.deliveryFailureCount, ownerUserId))),
      "last_delivery_failure_at_millis": millis(Keys.lastDeliveryFailureAt),
      "last_delivery_failure_reason": text(Keys.lastDeliveryFailureReason),
      "capacity_pressure": depth >= 800,
      "dropped_sample_count":
        Int64(defaults.integer(forKey: ownerKey(Keys.capacityDropCount, ownerUserId))),
      "last_drop_at_millis": millis(Keys.lastDropAt),
      "last_drop_reason": text(Keys.lastDropReason),
      "queue_corrupt": queueCorrupt,
      "queue_corrupt_reason": corruptReason,
      "queue_storage_unavailable": queueStorageUnavailable,
    ]
  }

  private func incrementMetric(
    ownerUserId: String,
    prefix: String,
    delta: Int64
  ) {
    let key = ownerKey(prefix, ownerUserId)
    let current = defaults.object(forKey: key) == nil
      ? 0
      : Int64(defaults.integer(forKey: key))
    defaults.set(current + delta, forKey: key)
  }

  private func beginTracking(
    ownerUserId: String,
    nowMillis: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
  ) {
    let key = ownerKey(Keys.trackingStartedAt, ownerUserId)
    if defaults.object(forKey: key) == nil {
      defaults.set(nowMillis, forKey: key)
    }
  }

  private func finishTracking(
    ownerUserId: String,
    nowMillis: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
  ) {
    let startedKey = ownerKey(Keys.trackingStartedAt, ownerUserId)
    guard defaults.object(forKey: startedKey) != nil else { return }
    let started = Int64(defaults.integer(forKey: startedKey))
    let elapsed = max(nowMillis - started, 0)
    let activeKey = ownerKey(Keys.metricActiveMs, ownerUserId)
    let accumulated = Int64(defaults.integer(forKey: activeKey))
    defaults.set(accumulated + elapsed, forKey: activeKey)
    defaults.removeObject(forKey: startedKey)
  }

  private func locationMetrics(ownerUserId: String) -> [String: Int64] {
    func value(_ prefix: String) -> Int64 {
      Int64(defaults.integer(forKey: ownerKey(prefix, ownerUserId)))
    }
    var activeMs = value(Keys.metricActiveMs)
    let startedKey = ownerKey(Keys.trackingStartedAt, ownerUserId)
    if defaults.object(forKey: startedKey) != nil {
      let started = Int64(defaults.integer(forKey: startedKey))
      let now = Int64(Date().timeIntervalSince1970 * 1000)
      activeMs += max(now - started, 0)
    }
    // Observability intentionally excludes coordinates, accuracy, speed and timestamps.
    return [
      "wakeups": value(Keys.metricWakeups),
      "samples_accepted": value(Keys.metricAccepted),
      "samples_dropped": value(Keys.metricDropped),
      "upload_batches": value(Keys.metricUploadBatches),
      "uploaded_samples": value(Keys.metricUploadedSamples),
      "active_tracking_ms": activeMs,
    ]
  }

  private func authorization() -> NativeLocationAuthorization {
    switch manager.authorizationStatus {
    case .notDetermined:
      return .notDetermined
    case .authorizedWhenInUse:
      return .foreground
    case .authorizedAlways:
      return .background
    case .denied:
      return .denied
    case .restricted:
      return .restricted
    @unknown default:
      return .restricted
    }
  }

  private func requestForegroundPermission(ownerUserId: String) -> [String: Any] {
    let current = authorization()
    if current == .notDetermined {
      // Foreground permission is the first stage and is only requested by this explicit
      // Flutter command. App launch/login/onboarding only call status().
      manager.requestWhenInUseAuthorization()
      return status(
        ownerUserId: ownerUserId,
        forcedReason: "foreground_permission_requested"
      )
    }
    return status(ownerUserId: ownerUserId)
  }

  private func enableAutomaticLocation(ownerUserId: String) -> [String: Any] {
    let current = authorization()
    if current == .background {
      switchAutomaticOwner(ownerUserId)
      return status(ownerUserId: ownerUserId)
    }

    guard NativeLocationPolicy.shouldRequestAlways(
      explicitAutomaticEnable: true,
      authorization: current
    ) else {
      return status(
        ownerUserId: ownerUserId,
        forcedReason: current == .denied || current == .restricted
          ? "permission_denied"
          : "foreground_permission_required"
      )
    }

    // requestAlwaysAuthorization is never chained from first launch or status refresh.
    // The only caller is the user's explicit "enable automatic location memory" action.
    pendingEnableOwnerUserId = ownerUserId
    manager.requestAlwaysAuthorization()
    return status(
      ownerUserId: ownerUserId,
      forcedReason: "background_permission_requested"
    )
  }

  private func switchAutomaticOwner(_ ownerUserId: String) {
    if enabledOwnerUserId != ownerUserId {
      stopProduction(runtimeAfterStop: .stopped)
      clearDiagnostics()
    }
    relaunchRestorePending = false
    enabledOwnerUserId = ownerUserId
  }

  private func clearDiagnostics() {
    defaults.removeObject(forKey: Keys.lastFixAt)
    defaults.removeObject(forKey: Keys.lastAccuracyMeters)
  }

  private func disableAutomaticLocation(ownerUserId: String) -> [String: Any] {
    if enabledOwnerUserId == ownerUserId || activeOwnerUserId == ownerUserId {
      stopProduction(runtimeAfterStop: .stopped)
      clearDiagnostics()
      if enabledOwnerUserId == ownerUserId {
        enabledOwnerUserId = nil
      }
      if pendingEnableOwnerUserId == ownerUserId {
        pendingEnableOwnerUserId = nil
      }
    }
    if #available(iOS 13.0, *) {
      PassiveMemoryBackgroundRecovery.cancel()
    }
    return status(ownerUserId: ownerUserId)
  }

  private func start(ownerUserId: String) -> [String: Any] {
    let current = authorization()
    let servicesEnabled = CLLocationManager.locationServicesEnabled()
    guard NativeLocationPolicy.canStart(
      ownerUserId: ownerUserId,
      enabledOwnerUserId: enabledOwnerUserId,
      authorization: current,
      locationServicesEnabled: servicesEnabled
    ) else {
      stopProduction(runtimeAfterStop: .stopped)
      return status(
        ownerUserId: ownerUserId,
        forcedReason: startFailureReason(
          ownerUserId: ownerUserId,
          authorization: current,
          locationServicesEnabled: servicesEnabled
        )
      )
    }

    if #available(iOS 13.0, *) {
      PassiveMemoryBackgroundRecovery.cancel()
    }
    // Significant-change monitoring remains the low-power recovery baseline. P may add
    // standard updates for moving states, but never removes this system relaunch foundation.
    manager.allowsBackgroundLocationUpdates = true
    manager.startMonitoringSignificantLocationChanges()
    let recoveredFrom =
      relaunchRestorePending
        ? "ios_location_relaunch"
        : nil
    nativeProducerActive = true
    relaunchRestorePending = false
    activeOwnerUserId = ownerUserId
    runtime = .running
    if let recoveredFrom {
      recordLifecycleDiagnostic(
        ownerUserId: ownerUserId,
        event: "recovery_result",
        reason: recoveredFrom,
        result: "running",
        success: true
      )
    }
    beginTracking(ownerUserId: ownerUserId)
    configureSamplingProfile(ownerUserId: ownerUserId)
    return status(ownerUserId: ownerUserId)
  }

  private func pause(ownerUserId: String) -> [String: Any] {
    if enabledOwnerUserId == ownerUserId || activeOwnerUserId == ownerUserId {
      stopProduction(runtimeAfterStop: .paused)
      if enabledOwnerUserId == ownerUserId {
        // Privacy pause/unknown is a quarantine. Keep only an owner-scoped recovery
        // hint; CoreLocation remains fully stopped until fresh server Privacy passes.
        activeOwnerUserId = ownerUserId
        relaunchRestorePending = true
        if #available(iOS 13.0, *) {
          PassiveMemoryBackgroundRecovery.schedule()
        }
      }
    }
    return status(ownerUserId: ownerUserId)
  }

  private func stop(ownerUserId: String) -> [String: Any] {
    if enabledOwnerUserId == ownerUserId || activeOwnerUserId == ownerUserId {
      stopProduction(runtimeAfterStop: .stopped)
    }
    if #available(iOS 13.0, *) {
      PassiveMemoryBackgroundRecovery.cancel()
    }
    return status(ownerUserId: ownerUserId)
  }

  private func stopProduction(runtimeAfterStop: NativeLocationRuntime) {
    manager.stopMonitoringSignificantLocationChanges()
    manager.stopUpdatingLocation()
    standardUpdatesActive = false
    if let activeOwnerUserId {
      finishTracking(ownerUserId: activeOwnerUserId)
    }
    manager.allowsBackgroundLocationUpdates = false
    nativeProducerActive = false
    relaunchRestorePending = false
    activeOwnerUserId = nil
    runtime = runtimeAfterStop
  }

  private func status(
    ownerUserId: String,
    forcedReason: String? = nil
  ) -> [String: Any] {
    let currentAuthorization = authorization()
    let servicesEnabled = CLLocationManager.locationServicesEnabled()
    let ownerMatches = enabledOwnerUserId == ownerUserId
    let activeOwnerMatches = activeOwnerUserId == ownerUserId

    if (nativeProducerActive || relaunchRestorePending) && !activeOwnerMatches {
      // A second account can never inherit either a running producer or a relaunch recovery hint.
      stopProduction(runtimeAfterStop: .stopped)
    } else if relaunchRestorePending &&
                (!ownerMatches ||
                 currentAuthorization != .background ||
                 !servicesEnabled) {
      // A pending relaunch is only a one-session recovery hint. Permission revocation,
      // disabled system location, or ownership mismatch invalidates it immediately.
      stopProduction(runtimeAfterStop: .stopped)
    }

    let reconciled = NativeLocationPolicy.reconcileRuntime(
      ownerUserId: ownerUserId,
      enabledOwnerUserId: enabledOwnerUserId,
      authorization: currentAuthorization,
      locationServicesEnabled: servicesEnabled,
      runtime: ownerMatches ? runtime : .stopped,
      nativeProducerActive: nativeProducerActive && activeOwnerMatches
    )

    if ownerMatches && runtime == .running && reconciled != .running {
      stopProduction(runtimeAfterStop: .stopped)
    }

    let reason = forcedReason ?? defaultReason(
      ownerUserId: ownerUserId,
      authorization: currentAuthorization,
      servicesEnabled: servicesEnabled,
      runtime: reconciled
    )

    var payload: [String: Any] = [
      "supported": true,
      "platform": "ios",
      "permission": permissionValue(currentAuthorization),
      "runtime": reconciled.rawValue,
      "automatic_enabled": ownerMatches,
      "location_services_enabled": servicesEnabled,
      "background_runtime_state": NativeLocationPolicy.recordingHealthBackgroundRuntime(
        authorization: currentAuthorization,
        locationServicesEnabled: servicesEnabled
      ),
      "battery_optimization_state": "not_applicable",
      "reason": reason ?? NSNull(),
      "restore_pending": ownerMatches && activeOwnerMatches && relaunchRestorePending,
      "recovery_reason":
        (ownerMatches && activeOwnerMatches && relaunchRestorePending)
          ? "ios_location_relaunch"
          : NSNull(),
      "queue": queueDiagnostics(ownerUserId: ownerUserId),
      "lifecycle": lifecycleDiagnostics(ownerUserId: ownerUserId),
    ]

    if ownerMatches {
      if let timestamp = defaults.object(forKey: Keys.lastFixAt) as? Date {
        payload["last_fix_at"] = ISO8601DateFormatter().string(from: timestamp)
      } else {
        payload["last_fix_at"] = NSNull()
      }
      if defaults.object(forKey: Keys.lastAccuracyMeters) != nil {
        payload["last_accuracy_meters"] =
          defaults.double(forKey: Keys.lastAccuracyMeters)
      } else {
        payload["last_accuracy_meters"] = NSNull()
      }
    } else {
      payload["last_fix_at"] = NSNull()
      payload["last_accuracy_meters"] = NSNull()
    }
    return payload
  }

  private func defaultReason(
    ownerUserId: String,
    authorization: NativeLocationAuthorization,
    servicesEnabled: Bool,
    runtime: NativeLocationRuntime
  ) -> String? {
    if !servicesEnabled { return "location_services_disabled" }
    switch authorization {
    case .notDetermined:
      return "foreground_permission_required"
    case .denied, .restricted:
      return "permission_denied"
    case .foreground:
      return enabledOwnerUserId == ownerUserId
        ? "background_permission_required"
        : "automatic_location_disabled"
    case .background:
      if enabledOwnerUserId != ownerUserId {
        return "automatic_location_disabled"
      }
      return runtime == .paused ? "paused" : nil
    }
  }

  private func startFailureReason(
    ownerUserId: String,
    authorization: NativeLocationAuthorization,
    locationServicesEnabled: Bool
  ) -> String {
    if !locationServicesEnabled { return "location_services_disabled" }
    if enabledOwnerUserId != ownerUserId { return "automatic_location_disabled" }
    switch authorization {
    case .background:
      return "native_start_failed"
    case .foreground:
      return "background_permission_required"
    case .notDetermined:
      return "foreground_permission_required"
    case .denied, .restricted:
      return "permission_denied"
    }
  }

  private func permissionValue(_ value: NativeLocationAuthorization) -> String {
    switch value {
    case .notDetermined:
      return "not_determined"
    case .foreground:
      return "foreground"
    case .background:
      return "background"
    case .denied:
      return "denied"
    case .restricted:
      return "restricted"
    }
  }

  func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
    let current = authorization()
    if current == .background, let pendingOwner = pendingEnableOwnerUserId {
      pendingEnableOwnerUserId = nil
      switchAutomaticOwner(pendingOwner)
    } else if current == .denied || current == .restricted ||
                current == .foreground {
      // If an Always request resolves without an Always grant, automatic location stays
      // disabled. We never reinterpret When-In-Use as background consent.
      pendingEnableOwnerUserId = nil
    }

    if runtime == .running {
      guard
        let owner = activeOwnerUserId,
        NativeLocationPolicy.canStart(
          ownerUserId: owner,
          enabledOwnerUserId: enabledOwnerUserId,
          authorization: current,
          locationServicesEnabled: CLLocationManager.locationServicesEnabled()
        )
      else {
        stopProduction(runtimeAfterStop: .stopped)
        return
      }
    }
  }

  func locationManager(
    _ manager: CLLocationManager,
    didUpdateLocations locations: [CLLocation]
  ) {
    guard
      let latest = locations.last,
      let activeOwnerUserId,
      activeOwnerUserId == enabledOwnerUserId,
      runtime == .running
    else {
      return
    }

    incrementMetric(
      ownerUserId: activeOwnerUserId,
      prefix: Keys.metricWakeups,
      delta: 1
    )
    let accuracy = NativeMotionSignalMapper.normalizedAccuracy(
      latest.horizontalAccuracy
    )
    let speed = NativeMotionSignalMapper.normalizedSpeed(latest.speed)
    defaults.set(latest.timestamp, forKey: Keys.lastFixAt)
    if let accuracy {
      defaults.set(accuracy, forKey: Keys.lastAccuracyMeters)
    } else {
      defaults.removeObject(forKey: Keys.lastAccuracyMeters)
    }

    let profile = samplingProfile(ownerUserId: activeOwnerUserId)
    let recordedAtMillis = Int64(latest.timestamp.timeIntervalSince1970 * 1000)
    setLatestMotionObservation(
      NativeMotionObservation(
        ownerUserId: activeOwnerUserId,
        accuracyMeters: accuracy,
        speedMetersPerSecond: speed,
        recordedAtMillis: recordedAtMillis
      )
    )
    let lastQueuedKey = ownerKey(Keys.lastQueuedAt, activeOwnerUserId)
    let lastQueued = defaults.object(forKey: lastQueuedKey) == nil
      ? nil
      : Int64(defaults.integer(forKey: lastQueuedKey))
    guard
      NativeLocationSampleAdmission.accepts(
        accuracyMeters: accuracy,
        profile: profile
      ),
      NativeLocationSampleAdmission.cadenceAllows(
        previousRecordedAtMillis: lastQueued,
        candidateRecordedAtMillis: recordedAtMillis,
        minIntervalMs: profile.minIntervalMs
      )
    else {
      incrementMetric(
        ownerUserId: activeOwnerUserId,
        prefix: Keys.metricDropped,
        delta: 1
      )
      channel?.invokeMethod("samplesAvailable", arguments: nil)
      return
    }

    let queued = enqueueLocationSample(
      NativeQueuedLocationSample(
        ownerUserId: activeOwnerUserId,
        clientUuid: UUID().uuidString.lowercased(),
        latitude: latest.coordinate.latitude,
        longitude: latest.coordinate.longitude,
        accuracyMeters: accuracy,
        speedMetersPerSecond: speed,
        recordedAtMillis: recordedAtMillis
      )
    )
    if queued {
      defaults.set(recordedAtMillis, forKey: lastQueuedKey)
      incrementMetric(
        ownerUserId: activeOwnerUserId,
        prefix: Keys.metricAccepted,
        delta: 1
      )
    } else {
      incrementMetric(
        ownerUserId: activeOwnerUserId,
        prefix: Keys.metricDropped,
        delta: 1
      )
    }
    channel?.invokeMethod("samplesAvailable", arguments: nil)
  }

  func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
    if let coreLocationError = error as? CLError,
       coreLocationError.code == .denied {
      stopProduction(runtimeAfterStop: .stopped)
    }
  }

  private enum Keys {
    static let enabledOwnerUserId = "native_location.enabled_owner_user_id"
    static let activeOwnerUserId = "native_location.active_owner_user_id"
    static let pendingEnableOwnerUserId = "native_location.pending_enable_owner_user_id"
    static let relaunchRestorePending = "native_location.relaunch_restore_pending"
    static let runtime = "native_location.runtime"
    static let lastFixAt = "native_location.last_fix_at"
    static let lastAccuracyMeters = "native_location.last_accuracy_meters"
    static let pendingSamples = "native_location.pending_samples"
    static let queueSchemaVersion = "native_location.pending_samples_schema_version"
    static let nextQueueSequence = "native_location.pending_samples_next_sequence"
    static let queueCorrupt = "native_location.pending_samples_corrupt"
    static let queueCorruptReason = "native_location.pending_samples_corrupt_reason"
    static let queueCorruptAt = "native_location.pending_samples_corrupt_at"
    static let samplingProfile = "native_location.sampling_profile"
    static let latestMotionObservation = "native_location.latest_motion_observation"
    static let metricWakeups = "native_location.metric_wakeups"
    static let metricAccepted = "native_location.metric_samples_accepted"
    static let metricDropped = "native_location.metric_samples_dropped"
    static let metricUploadBatches = "native_location.metric_upload_batches"
    static let metricUploadedSamples = "native_location.metric_uploaded_samples"
    static let metricActiveMs = "native_location.metric_active_tracking_ms"
    static let trackingStartedAt = "native_location.tracking_started_at"
    static let lastQueuedAt = "native_location.last_queued_at"
    static let lastEnqueueAt = "native_location.last_enqueue_at"
    static let lastDeliveryAt = "native_location.last_delivery_at"
    static let deliveryFailureCount = "native_location.delivery_failure_count"
    static let lastDeliveryFailureAt = "native_location.last_delivery_failure_at"
    static let lastDeliveryFailureReason = "native_location.last_delivery_failure_reason"
    static let capacityDropCount = "native_location.capacity_drop_count"
    static let lastDropAt = "native_location.last_drop_at"
    static let lastDropReason = "native_location.last_drop_reason"
    static let lifecyclePauseCount = "native_location.lifecycle_pause_count"
    static let lifecycleLastPauseAt = "native_location.lifecycle_last_pause_at"
    static let lifecycleLastPauseReason = "native_location.lifecycle_last_pause_reason"
    static let lifecycleRecoveryAttemptCount =
      "native_location.lifecycle_recovery_attempt_count"
    static let lifecycleLastRecoveryAt = "native_location.lifecycle_last_recovery_at"
    static let lifecycleLastRecoveryReason =
      "native_location.lifecycle_last_recovery_reason"
    static let lifecycleLastRecoveryResult =
      "native_location.lifecycle_last_recovery_result"
    static let lifecycleLastRecoverySuccessAt =
      "native_location.lifecycle_last_recovery_success_at"
    static let lifecycleDisableCount = "native_location.lifecycle_disable_count"
    static let lifecycleLastDisableAt = "native_location.lifecycle_last_disable_at"
    static let lifecycleLastDisableReason = "native_location.lifecycle_last_disable_reason"
  }
}


enum NativeNotificationPolicy {
  static func permissionWire(_ status: UNAuthorizationStatus) -> String {
    switch status {
    case .notDetermined:
      return "notDetermined"
    case .denied:
      return "denied"
    case .authorized:
      return "authorized"
    case .provisional:
      return "provisional"
    @unknown default:
      if #available(iOS 14.0, *), status == .ephemeral {
        return "provisional"
      }
      return "unavailable"
    }
  }

  static func tokenHex(_ data: Data) -> String {
    data.map { String(format: "%02x", $0) }.joined()
  }

  static func mayRegister(_ status: UNAuthorizationStatus) -> Bool {
    switch status {
    case .authorized, .provisional:
      return true
    default:
      if #available(iOS 14.0, *), status == .ephemeral {
        return true
      }
      return false
    }
  }
}

final class NativeNotificationBridge: NSObject, UNUserNotificationCenterDelegate {
  static let shared = NativeNotificationBridge()

  private let channelName = "cn.jiyidashi/notifications"
  private let pendingTapKey = "jiyi.push.pending_tap.v1"
  private let allowedDestinations: Set<String> = [
    "HOME", "REMINDER", "MEMORY", "APP_UPDATE", "FAMILY", "EXPORT",
  ]
  private var channel: FlutterMethodChannel?
  private var dartReady = false
  private var currentToken: String?

  private override init() {
    super.init()
  }

  func installNotificationCenterDelegate() {
    UNUserNotificationCenter.current().delegate = self
  }

  func attach(messenger: FlutterBinaryMessenger) {
    let methodChannel = FlutterMethodChannel(
      name: channelName,
      binaryMessenger: messenger
    )
    methodChannel.setMethodCallHandler { [weak self] call, result in
      guard let self else {
        result(
          FlutterError(
            code: "push_bridge_unavailable",
            message: "Push bridge is unavailable",
            details: nil
          )
        )
        return
      }
      switch call.method {
      case "ready":
        self.dartReady = true
        self.deliverPendingTapIfNeeded()
        result(nil)
      case "status":
        self.status(result: result)
      case "requestPermission":
        self.requestPermission(result: result)
      case "registerForPush":
        self.registerForPush(result: result)
      case "unregisterFromPush":
        self.unregisterFromPush(result: result)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
    channel = methodChannel
  }

  func didRegister(deviceToken: Data) {
    let token = NativeNotificationPolicy.tokenHex(deviceToken)
    currentToken = token
    emitStatus(method: "token")
  }

  func didFailToRegister() {
    currentToken = nil
    emitStatus(method: "token")
  }

  func captureLaunchTap(_ userInfo: [AnyHashable: Any]) {
    guard let payload = canonicalPayload(userInfo) else { return }
    persistPendingTap(
      payload: payload,
      eventId: UUID().uuidString
    )
  }

  func captureSceneTap(_ response: UNNotificationResponse) {
    let payload = response.notification.request.content.userInfo
    guard let canonical = canonicalPayload(payload) else { return }
    publishTap(
      payload: canonical,
      eventId: response.notification.request.identifier
    )
  }

  private func statusMap(
    authorization: UNAuthorizationStatus
  ) -> [String: Any?] {
    let bundle = Bundle.main
    return [
      "supported": true,
      "platform": "IOS",
      "permission": NativeNotificationPolicy.permissionWire(authorization),
      "provider": "APNS",
      "token": currentToken,
      "app_version":
        bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
      "os_version": UIDevice.current.systemVersion,
    ]
  }

  private func status(result: @escaping FlutterResult) {
    UNUserNotificationCenter.current().getNotificationSettings { settings in
      DispatchQueue.main.async {
        result(self.statusMap(authorization: settings.authorizationStatus))
      }
    }
  }

  private func emitStatus(method: String) {
    guard dartReady else { return }
    UNUserNotificationCenter.current().getNotificationSettings { settings in
      let body = self.statusMap(authorization: settings.authorizationStatus)
      DispatchQueue.main.async {
        self.channel?.invokeMethod(method, arguments: body)
      }
    }
  }

  private func requestPermission(result: @escaping FlutterResult) {
    UNUserNotificationCenter.current().requestAuthorization(
      options: [.alert, .badge, .sound]
    ) { _, _ in
      self.emitStatus(method: "permission")
      self.status(result: result)
    }
  }

  private func registerForPush(result: @escaping FlutterResult) {
    UNUserNotificationCenter.current().getNotificationSettings { settings in
      guard NativeNotificationPolicy.mayRegister(
        settings.authorizationStatus
      ) else {
        DispatchQueue.main.async {
          result(self.statusMap(authorization: settings.authorizationStatus))
        }
        return
      }
      DispatchQueue.main.async {
        UIApplication.shared.registerForRemoteNotifications()
        result(self.statusMap(authorization: settings.authorizationStatus))
      }
    }
  }

  private func unregisterFromPush(result: @escaping FlutterResult) {
    DispatchQueue.main.async {
      UIApplication.shared.unregisterForRemoteNotifications()
      self.currentToken = nil
      result(nil)
      self.emitStatus(method: "token")
    }
  }

  func canonicalPayload(
    _ userInfo: [AnyHashable: Any]
  ) -> [String: Any]? {
    let version: Int?
    if let raw = userInfo["version"] as? NSNumber {
      version = raw.intValue
    } else if let raw = userInfo["version"] as? String {
      version = Int(raw)
    } else {
      version = nil
    }
    guard version == 1 else { return nil }

    var destination = (userInfo["destination"] as? String)?.uppercased() ?? "HOME"
    if !allowedDestinations.contains(destination) {
      destination = "HOME"
    }

    var resourceId: String?
    if let raw = userInfo["resource_id"] as? String, !raw.isEmpty {
      guard UUID(uuidString: raw) != nil else {
        return [
          "version": 1,
          "destination": "HOME",
        ]
      }
      resourceId = raw
    }
    if destination == "MEMORY" && resourceId == nil {
      destination = "HOME"
    }

    var result: [String: Any] = [
      "version": 1,
      "destination": destination,
    ]
    if let resourceId {
      result["resource_id"] = resourceId
    }
    return result
  }

  private func persistPendingTap(
    payload: [String: Any],
    eventId: String
  ) {
    UserDefaults.standard.set(
      [
        "payload": payload,
        "event_id": eventId,
      ],
      forKey: pendingTapKey
    )
  }

  private func publishTap(
    payload: [String: Any],
    eventId: String
  ) {
    guard dartReady, let channel else {
      persistPendingTap(payload: payload, eventId: eventId)
      return
    }
    channel.invokeMethod(
      "tap",
      arguments: [
        "payload": payload,
        "event_id": eventId,
      ]
    )
  }

  private func deliverPendingTapIfNeeded() {
    guard
      dartReady,
      let pending = UserDefaults.standard.dictionary(forKey: pendingTapKey),
      let payload = pending["payload"] as? [String: Any],
      let eventId = pending["event_id"] as? String
    else {
      return
    }
    UserDefaults.standard.removeObject(forKey: pendingTapKey)
    channel?.invokeMethod(
      "tap",
      arguments: [
        "payload": payload,
        "event_id": eventId,
      ]
    )
  }

  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification,
    withCompletionHandler completionHandler:
      @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    if
      let payload = canonicalPayload(notification.request.content.userInfo),
      dartReady
    {
      channel?.invokeMethod(
        "notification",
        arguments: [
          "payload": payload,
          "event_id": notification.request.identifier,
        ]
      )
    }
    if #available(iOS 14.0, *) {
      completionHandler([.banner, .sound, .badge])
    } else {
      completionHandler([.alert, .sound, .badge])
    }
  }

  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    didReceive response: UNNotificationResponse,
    withCompletionHandler completionHandler: @escaping () -> Void
  ) {
    captureSceneTap(response)
    completionHandler()
  }
}

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var nativeLocationBridge: NativeLocationBridge?
  private let nativeNotificationBridge = NativeNotificationBridge.shared
  private var activePassiveRecoveryTask: BGAppRefreshTask?
  private var passiveRecoveryCompletionChannel: FlutterMethodChannel?

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    nativeNotificationBridge.installNotificationCenterDelegate()
    if let remote = launchOptions?[.remoteNotification] as? [AnyHashable: Any] {
      nativeNotificationBridge.captureLaunchTap(remote)
    }

    if #available(iOS 13.0, *) {
      BGTaskScheduler.shared.register(
        forTaskWithIdentifier: PassiveMemoryBackgroundRecovery.identifier,
        using: nil
      ) { [weak self] task in
        guard let refreshTask = task as? BGAppRefreshTask else {
          task.setTaskCompleted(success: false)
          return
        }
        self?.handlePassiveRecoveryTask(refreshTask)
      }
    }

    let bridge = NativeLocationBridge()
    bridge.onPassiveRecoveryReady = { [weak self] in
      self?.dispatchPassiveRecoveryIfReady()
    }
    nativeLocationBridge = bridge
    if launchOptions?[.location] != nil {
      // iOS can relaunch a terminated app before Flutter can verify authoritative privacy.
      // Record only that the old producer was eligible to recover; do not start CoreLocation
      // until the authenticated Flutter shell confirms server privacy is active.
      bridge.markLocationRelaunchRestorePending()
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    nativeNotificationBridge.attach(
      messenger: engineBridge.applicationRegistrar.messenger()
    )

    let bridge = nativeLocationBridge ?? NativeLocationBridge()
    bridge.onPassiveRecoveryReady = { [weak self] in
      self?.dispatchPassiveRecoveryIfReady()
    }
    bridge.attach(messenger: engineBridge.applicationRegistrar.messenger())
    nativeLocationBridge = bridge

    let completionChannel = FlutterMethodChannel(
      name: "cn.jiyidashi/passive_recovery",
      binaryMessenger: engineBridge.applicationRegistrar.messenger()
    )
    completionChannel.setMethodCallHandler { [weak self] call, result in
      guard call.method == "complete" else {
        result(FlutterMethodNotImplemented)
        return
      }
      let arguments = call.arguments as? [String: Any]
      let retry = arguments?["retry"] as? Bool ?? true
      let status = arguments?["status"] as? String ?? "unknown"
      if status == "accountDeletionInProgress" {
        self?.nativeLocationBridge?.disableAutomaticProductionForAccountDeletion()
      } else if status == "noSession" || status == "authorityChanged" {
        self?.nativeLocationBridge?.sealAutomaticProductionForAuthorityLoss()
      }
      self?.finishPassiveRecoveryTask(success: !retry, retry: retry)
      result(nil)
    }
    passiveRecoveryCompletionChannel = completionChannel
  }

  @available(iOS 13.0, *)
  private func handlePassiveRecoveryTask(_ task: BGAppRefreshTask) {
    if activePassiveRecoveryTask != nil {
      PassiveMemoryBackgroundRecovery.schedule()
      task.setTaskCompleted(success: false)
      return
    }
    activePassiveRecoveryTask = task
    task.expirationHandler = { [weak self] in
      self?.finishPassiveRecoveryTask(success: false, retry: true)
    }
    dispatchPassiveRecoveryIfReady()
  }

  private func dispatchPassiveRecoveryIfReady() {
    guard #available(iOS 13.0, *),
          activePassiveRecoveryTask != nil
    else {
      return
    }
    // The bridge returns false until Dart has installed its MethodChannel handler.
    // Keep the BG task alive until that handshake or expiration; never treat "not ready"
    // as permission to skip the AUTH/Privacy recovery check.
    _ = nativeLocationBridge?.requestPassiveRecoveryWakeup()
  }

  override func application(
    _ application: UIApplication,
    didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
  ) {
    nativeNotificationBridge.didRegister(deviceToken: deviceToken)
    super.application(
      application,
      didRegisterForRemoteNotificationsWithDeviceToken: deviceToken
    )
  }

  override func application(
    _ application: UIApplication,
    didFailToRegisterForRemoteNotificationsWithError error: Error
  ) {
    nativeNotificationBridge.didFailToRegister()
    super.application(
      application,
      didFailToRegisterForRemoteNotificationsWithError: error
    )
  }

  private func finishPassiveRecoveryTask(
    success: Bool,
    retry: Bool
  ) {
    guard #available(iOS 13.0, *),
          let task = activePassiveRecoveryTask
    else {
      return
    }
    activePassiveRecoveryTask = nil
    task.expirationHandler = nil
    if retry {
      PassiveMemoryBackgroundRecovery.schedule()
    }
    task.setTaskCompleted(success: success)
  }
}
