import Flutter
import UIKit
import WechatOpenSDK

enum WechatIOSAuthState: String {
  case available = "AVAILABLE"
  case unavailable = "UNAVAILABLE"
  case cancelled = "CANCELLED"
  case timeout = "TIMEOUT"
  case providerError = "PROVIDER_ERROR"
  case credentialAcquired = "CREDENTIAL_ACQUIRED"
}

struct WechatIOSAuthResult {
  let state: WechatIOSAuthState
  let credential: String?
  let reason: String?

  init(
    state: WechatIOSAuthState,
    credential: String? = nil,
    reason: String? = nil
  ) {
    self.state = state
    self.credential = credential
    self.reason = reason
  }

  func platformMap() -> [String: Any] {
    var value: [String: Any] = ["state": state.rawValue]
    if let credential, !credential.isEmpty {
      value["credential"] = credential
    }
    if let reason, !reason.isEmpty {
      value["reason"] = reason
    }
    return value
  }
}

struct WechatIOSConfiguration: Equatable {
  let appId: String?
  let universalLink: String?
  let provider: String
  let liveEnabled: Bool

  static func fromBundle(_ bundle: Bundle = .main) -> WechatIOSConfiguration {
    func configuredString(_ key: String) -> String? {
      guard let value = bundle.object(forInfoDictionaryKey: key) as? String else {
        return nil
      }
      let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmed.isEmpty, !trimmed.contains("$(") else { return nil }
      return trimmed
    }

    let provider = configuredString("AUTH_WECHAT_PROVIDER") ?? "disabled"
    let liveValue = configuredString("JIYI_WECHAT_LIVE_ENABLED") ?? "false"
    let liveEnabled = ["1", "true", "yes"].contains(liveValue.lowercased())
    return WechatIOSConfiguration(
      appId: configuredString("JIYI_WECHAT_APP_ID"),
      universalLink: configuredString("JIYI_WECHAT_UNIVERSAL_LINK"),
      provider: provider,
      liveEnabled: liveEnabled
    )
  }

  var isConfigured: Bool {
    guard liveEnabled,
          provider.caseInsensitiveCompare("wechat") == .orderedSame,
          let appId,
          !appId.isEmpty,
          let universalLink,
          let url = URL(string: universalLink),
          url.scheme?.lowercased() == "https",
          url.host != nil,
          url.query == nil,
          url.fragment == nil,
          !url.path.isEmpty
    else {
      return false
    }
    return true
  }

  var unavailableReason: String {
    if !liveEnabled || provider.caseInsensitiveCompare("wechat") != .orderedSame {
      return "WECHAT_PROVIDER_DISABLED"
    }
    if appId == nil || appId?.isEmpty == true {
      return "WECHAT_APP_ID_MISSING"
    }
    guard let universalLink,
          let url = URL(string: universalLink),
          url.scheme?.lowercased() == "https",
          url.host != nil,
          url.query == nil,
          url.fragment == nil,
          !url.path.isEmpty
    else {
      return "WECHAT_UNIVERSAL_LINK_INVALID"
    }
    return "WECHAT_NOT_CONFIGURED"
  }
}

protocol WechatIOSSDKClientProtocol: AnyObject {
  func registerApp(appId: String, universalLink: String) -> Bool
  func isWXAppInstalled() -> Bool
  func isWXAppSupportAPI() -> Bool
  func sendAuthRequest(
    state: String,
    presenter: UIViewController,
    delegate: WXApiDelegate,
    completion: @escaping (Bool) -> Void
  )
  func handleOpenURL(_ url: URL, delegate: WXApiDelegate) -> Bool
  func handleOpenUniversalLink(
    _ userActivity: NSUserActivity,
    delegate: WXApiDelegate
  ) -> Bool
}

final class WechatIOSSDKClient: WechatIOSSDKClientProtocol {
  func registerApp(appId: String, universalLink: String) -> Bool {
    WXApi.registerApp(appId, universalLink: universalLink)
  }

  func isWXAppInstalled() -> Bool {
    WXApi.isWXAppInstalled()
  }

  func isWXAppSupportAPI() -> Bool {
    WXApi.isWXAppSupport()
  }

  func sendAuthRequest(
    state: String,
    presenter: UIViewController,
    delegate: WXApiDelegate,
    completion: @escaping (Bool) -> Void
  ) {
    let request = SendAuthReq()
    request.scope = "snsapi_userinfo"
    request.state = state
    WXApi.sendAuthReq(
      request,
      viewController: presenter,
      delegate: delegate,
      completion: completion
    )
  }

  func handleOpenURL(_ url: URL, delegate: WXApiDelegate) -> Bool {
    WXApi.handleOpen(url, delegate: delegate)
  }

  func handleOpenUniversalLink(
    _ userActivity: NSUserActivity,
    delegate: WXApiDelegate
  ) -> Bool {
    WXApi.handleOpenUniversalLink(userActivity, delegate: delegate)
  }
}

protocol WechatIOSAuthScheduler {
  func schedule(after seconds: TimeInterval, _ task: @escaping () -> Void) -> () -> Void
}

final class DispatchWechatIOSAuthScheduler: WechatIOSAuthScheduler {
  func schedule(after seconds: TimeInterval, _ task: @escaping () -> Void) -> () -> Void {
    let work = DispatchWorkItem(block: task)
    DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    return { work.cancel() }
  }
}

final class WechatAuthNativeBridge: NSObject, WXApiDelegate {
  static let shared = WechatAuthNativeBridge()

  private struct PendingRequest {
    let generation: UInt64
    let state: String
    let completion: (WechatIOSAuthResult) -> Void
    let cancelTimeout: () -> Void
    var externalHandoff: Bool
  }

  private let configuration: WechatIOSConfiguration
  private let sdk: WechatIOSSDKClientProtocol
  private let scheduler: WechatIOSAuthScheduler
  private let requestTimeout: TimeInterval
  private var channel: FlutterMethodChannel?
  private var viewControllerProvider: (() -> UIViewController?)?
  private var pending: PendingRequest?
  private var nextGeneration: UInt64 = 0
  private var privacyGranted = false
  private var initialized = false

  init(
    configuration: WechatIOSConfiguration = .fromBundle(),
    sdk: WechatIOSSDKClientProtocol = WechatIOSSDKClient(),
    scheduler: WechatIOSAuthScheduler = DispatchWechatIOSAuthScheduler(),
    requestTimeout: TimeInterval = 60,
    viewControllerProvider: (() -> UIViewController?)? = nil
  ) {
    self.configuration = configuration
    self.sdk = sdk
    self.scheduler = scheduler
    self.requestTimeout = requestTimeout
    self.viewControllerProvider = viewControllerProvider
    super.init()
  }

  func attach(
    messenger: FlutterBinaryMessenger,
    viewControllerProvider: @escaping () -> UIViewController?
  ) {
    self.viewControllerProvider = viewControllerProvider
    channel?.setMethodCallHandler(nil)
    let methodChannel = FlutterMethodChannel(
      name: "cn.jiyidashi/wechat_auth",
      binaryMessenger: messenger
    )
    methodChannel.setMethodCallHandler { [weak self] call, result in
      self?.handle(call: call, result: result)
    }
    channel = methodChannel
  }

  func detach() {
    invalidateForLifecycle(reason: "ENGINE_DETACHED")
    channel?.setMethodCallHandler(nil)
    channel = nil
    viewControllerProvider = nil
  }

  func handle(call: FlutterMethodCall, result: @escaping FlutterResult) {
    switch call.method {
    case "initialize":
      let privacy = (call.arguments as? [String: Any])?["privacy_consent_granted"] as? Bool == true
      if privacy {
        initialize(result: result)
      } else {
        revokePrivacy(result: result)
      }
    case "checkAvailability":
      checkAvailability(result: result)
    case "requestCredential":
      requestCredential(result: result)
    case "cancel":
      cancel(result: result)
    case "revokePrivacy":
      revokePrivacy(result: result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  func handleOpenURL(_ url: URL) -> Bool {
    guard configuration.isConfigured, pending != nil else { return false }
    return sdk.handleOpenURL(url, delegate: self)
  }

  func handleOpenUniversalLink(_ userActivity: NSUserActivity) -> Bool {
    guard configuration.isConfigured, pending != nil else { return false }
    return sdk.handleOpenUniversalLink(userActivity, delegate: self)
  }

  func markExternalProviderReturned() {
    pending?.externalHandoff = false
  }

  func invalidateForLifecycle(reason: String) {
    if reason == "APP_BACKGROUND", pending?.externalHandoff == true {
      return
    }
    guard let generation = pending?.generation else { return }
    complete(
      generation: generation,
      result: WechatIOSAuthResult(state: .cancelled, reason: reason)
    )
  }

  func handleProviderResponse(
    errorCode: Int,
    state: String?,
    credential: String?
  ) {
    guard let request = pending, state == request.state else {
      return
    }
    switch errorCode {
    case 0:
      guard let credential, !credential.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        complete(
          generation: request.generation,
          result: WechatIOSAuthResult(state: .providerError, reason: "MISSING_CREDENTIAL")
        )
        return
      }
      complete(
        generation: request.generation,
        result: WechatIOSAuthResult(state: .credentialAcquired, credential: credential)
      )
    case -2:
      complete(
        generation: request.generation,
        result: WechatIOSAuthResult(state: .cancelled, reason: "USER_CANCELLED")
      )
    case -4:
      complete(
        generation: request.generation,
        result: WechatIOSAuthResult(state: .providerError, reason: "AUTH_DENIED")
      )
    default:
      complete(
        generation: request.generation,
        result: WechatIOSAuthResult(state: .providerError, reason: "CALLBACK_ERROR")
      )
    }
  }

  func onReq(_ req: BaseReq) {}

  func onResp(_ resp: BaseResp) {
    guard let authResponse = resp as? SendAuthResp else { return }
    handleProviderResponse(
      errorCode: Int(resp.errCode),
      state: authResponse.state,
      credential: authResponse.code
    )
  }

  private func initialize(result: @escaping FlutterResult) {
    guard pending == nil else {
      result(unavailable(reason: "REQUEST_IN_PROGRESS").platformMap())
      return
    }
    privacyGranted = true
    guard configuration.isConfigured,
          let appId = configuration.appId,
          let universalLink = configuration.universalLink
    else {
      initialized = false
      result(unavailable(reason: configuration.unavailableReason).platformMap())
      return
    }
    let registered = sdk.registerApp(appId: appId, universalLink: universalLink)
    initialized = registered
    result(
      registered
        ? WechatIOSAuthResult(state: .available).platformMap()
        : unavailable(reason: "SDK_REGISTER_FAILED").platformMap()
    )
  }

  private func checkAvailability(result: @escaping FlutterResult) {
    guard privacyGranted else {
      result(unavailable(reason: "PRIVACY_NOT_ACCEPTED").platformMap())
      return
    }
    guard initialized else {
      result(unavailable(reason: "NOT_INITIALIZED").platformMap())
      return
    }
    guard sdk.isWXAppInstalled() else {
      result(unavailable(reason: "WECHAT_NOT_INSTALLED").platformMap())
      return
    }
    guard sdk.isWXAppSupportAPI() else {
      result(unavailable(reason: "WECHAT_API_UNSUPPORTED").platformMap())
      return
    }
    result(WechatIOSAuthResult(state: .available).platformMap())
  }

  private func requestCredential(result: @escaping FlutterResult) {
    guard privacyGranted, initialized, configuration.isConfigured else {
      result(unavailable(reason: privacyGranted ? "NOT_AVAILABLE" : "PRIVACY_NOT_ACCEPTED").platformMap())
      return
    }
    guard pending == nil else {
      result(unavailable(reason: "REQUEST_IN_PROGRESS").platformMap())
      return
    }
    guard let presenter = viewControllerProvider?() else {
      result(unavailable(reason: "VIEW_CONTROLLER_UNAVAILABLE").platformMap())
      return
    }

    nextGeneration &+= 1
    let generation = nextGeneration
    let state = UUID().uuidString
    let cancelTimeout = scheduler.schedule(after: requestTimeout) { [weak self] in
      self?.complete(
        generation: generation,
        result: WechatIOSAuthResult(state: .timeout)
      )
    }
    pending = PendingRequest(
      generation: generation,
      state: state,
      completion: { value in result(value.platformMap()) },
      cancelTimeout: cancelTimeout,
      externalHandoff: false
    )
    sdk.sendAuthRequest(
      state: state,
      presenter: presenter,
      delegate: self
    ) { [weak self] accepted in
      guard let self, self.pending?.generation == generation else { return }
      if accepted {
        self.pending?.externalHandoff = true
      } else {
        self.complete(
          generation: generation,
          result: WechatIOSAuthResult(state: .providerError, reason: "REQUEST_REJECTED")
        )
      }
    }
  }

  private func cancel(result: @escaping FlutterResult) {
    guard let generation = pending?.generation else {
      result(WechatIOSAuthResult(state: .cancelled).platformMap())
      return
    }
    complete(
      generation: generation,
      result: WechatIOSAuthResult(state: .cancelled, reason: "USER_CANCELLED")
    )
    result(WechatIOSAuthResult(state: .cancelled).platformMap())
  }

  private func revokePrivacy(result: @escaping FlutterResult) {
    privacyGranted = false
    initialized = false
    if let generation = pending?.generation {
      complete(
        generation: generation,
        result: WechatIOSAuthResult(state: .cancelled, reason: "PRIVACY_REVOKED")
      )
    }
    result(unavailable(reason: "PRIVACY_REVOKED").platformMap())
  }

  private func complete(generation: UInt64, result: WechatIOSAuthResult) {
    guard let request = pending, request.generation == generation else { return }
    pending = nil
    request.cancelTimeout()
    request.completion(result)
  }

  private func unavailable(reason: String) -> WechatIOSAuthResult {
    WechatIOSAuthResult(state: .unavailable, reason: reason)
  }
}
