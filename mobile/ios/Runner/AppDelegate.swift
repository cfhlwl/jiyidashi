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

    // Significant-change monitoring is the Stage 2 foundation: it is system-driven and
    // low-frequency. Motion-aware sampling and upload contracts belong to later S2 lines.
    manager.allowsBackgroundLocationUpdates = true
    manager.startMonitoringSignificantLocationChanges()
    nativeProducerActive = true
    relaunchRestorePending = false
    activeOwnerUserId = ownerUserId
    runtime = .running
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
      activeOwnerUserId == enabledOwnerUserId
    else {
      return
    }
    // Raw coordinates are intentionally not persisted in this foundation PR. Until S2-006
    // defines the owner-scoped sync/lifecycle contract, only non-location diagnostics survive.
    defaults.set(latest.timestamp, forKey: Keys.lastFixAt)
    defaults.set(latest.horizontalAccuracy, forKey: Keys.lastAccuracyMeters)
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
