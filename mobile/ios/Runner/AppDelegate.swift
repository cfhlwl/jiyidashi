import CoreLocation
import Flutter
import UIKit

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
    // Server privacy is not known yet, so relaunch must remain stopped until Flutter verifies it.
    return NativeLocationRelaunchState(
      restorePending: true,
      runtime: .stopped
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
  private var channel: FlutterMethodChannel?
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
    let nextChannel = FlutterMethodChannel(
      name: "cn.jiyidashi/native_location",
      binaryMessenger: messenger
    )
    nextChannel.setMethodCallHandler { [weak self] call, result in
      self?.handle(call: call, result: result)
    }
    channel = nextChannel
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
      }
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
    return pendingLocationSamples(ownerUserId: ownerUserId)
      .prefix(limit)
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
    savePendingLocationSamples(retained)
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

  private func allPendingLocationSamples() -> [NativeQueuedLocationSample] {
    guard
      let data = defaults.data(forKey: Keys.pendingSamples),
      let samples = try? JSONDecoder().decode(
        [NativeQueuedLocationSample].self,
        from: data
      )
    else {
      return []
    }
    return samples
  }

  private func savePendingLocationSamples(
    _ samples: [NativeQueuedLocationSample]
  ) {
    if let data = try? JSONEncoder().encode(samples) {
      defaults.set(data, forKey: Keys.pendingSamples)
    }
  }

  private func pendingLocationSamples(
    ownerUserId: String
  ) -> [NativeQueuedLocationSample] {
    allPendingLocationSamples().filter { $0.ownerUserId == ownerUserId }
  }

  private func enqueueLocationSample(
    _ sample: NativeQueuedLocationSample
  ) -> Bool {
    var samples = allPendingLocationSamples()
    if samples.contains(where: {
      $0.ownerUserId == sample.ownerUserId &&
        $0.clientUuid == sample.clientUuid
    }) {
      return true
    }
    guard NativeOwnerQueueQuota.hasCapacity(
      samples: samples,
      ownerUserId: sample.ownerUserId,
      maxPerOwner: 1000
    ) else {
      return false
    }
    samples.append(sample)
    savePendingLocationSamples(samples)
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
    savePendingLocationSamples(
      allPendingLocationSamples().filter { $0.ownerUserId != ownerUserId }
    )
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
    ]
    for prefix in prefixes {
      defaults.removeObject(forKey: ownerKey(prefix, ownerUserId))
    }
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

    // Significant-change monitoring remains the low-power recovery baseline. P may add
    // standard updates for moving states, but never removes this system relaunch foundation.
    manager.allowsBackgroundLocationUpdates = true
    manager.startMonitoringSignificantLocationChanges()
    nativeProducerActive = true
    relaunchRestorePending = false
    activeOwnerUserId = ownerUserId
    runtime = .running
    beginTracking(ownerUserId: ownerUserId)
    configureSamplingProfile(ownerUserId: ownerUserId)
    return status(ownerUserId: ownerUserId)
  }

  private func pause(ownerUserId: String) -> [String: Any] {
    if enabledOwnerUserId == ownerUserId || activeOwnerUserId == ownerUserId {
      stopProduction(runtimeAfterStop: .paused)
    }
    return status(ownerUserId: ownerUserId)
  }

  private func stop(ownerUserId: String) -> [String: Any] {
    if enabledOwnerUserId == ownerUserId || activeOwnerUserId == ownerUserId {
      stopProduction(runtimeAfterStop: .stopped)
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
      "reason": reason ?? NSNull(),
      "restore_pending": ownerMatches && activeOwnerMatches && relaunchRestorePending,
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
  }
}

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var nativeLocationBridge: NativeLocationBridge?

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    let bridge = NativeLocationBridge()
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

    let bridge = nativeLocationBridge ?? NativeLocationBridge()
    bridge.attach(messenger: engineBridge.applicationRegistrar.messenger())
    nativeLocationBridge = bridge
  }
}
