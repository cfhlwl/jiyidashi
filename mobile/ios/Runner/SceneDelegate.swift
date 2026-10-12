import Flutter
import UIKit
import UserNotifications

enum WechatSceneURLRouter {
  struct Partition: Equatable {
    let consumed: Set<URL>
    let unconsumed: [URL]
  }

  static func partition(
    _ urls: [URL],
    handle: (URL) -> Bool
  ) -> Partition {
    var consumed = Set<URL>()
    var unconsumed: [URL] = []
    for url in urls {
      if consumed.contains(url) {
        continue
      }
      if handle(url) {
        consumed.insert(url)
      } else {
        unconsumed.append(url)
      }
    }
    return Partition(consumed: consumed, unconsumed: unconsumed)
  }
}

class SceneDelegate: FlutterSceneDelegate {
  override func scene(
    _ scene: UIScene,
    willConnectTo session: UISceneSession,
    options connectionOptions: UIScene.ConnectionOptions
  ) {
    if let response = connectionOptions.notificationResponse {
      NativeNotificationBridge.shared.captureSceneTap(response)
    }
    super.scene(
      scene,
      willConnectTo: session,
      options: connectionOptions
    )

    for userActivity in connectionOptions.userActivities {
      _ = WechatAuthNativeBridge.shared.handleOpenUniversalLink(userActivity)
    }
    for context in connectionOptions.urlContexts {
      _ = WechatAuthNativeBridge.shared.handleOpenURL(context.url)
    }
  }

  override func sceneWillEnterForeground(_ scene: UIScene) {
    WechatAuthNativeBridge.shared.markExternalProviderReturned()
    super.sceneWillEnterForeground(scene)
  }

  override func sceneDidEnterBackground(_ scene: UIScene) {
    WechatAuthNativeBridge.shared.invalidateForLifecycle(reason: "APP_BACKGROUND")
    super.sceneDidEnterBackground(scene)
  }

  override func scene(
    _ scene: UIScene,
    continue userActivity: NSUserActivity
  ) {
    if !WechatAuthNativeBridge.shared.handleOpenUniversalLink(userActivity) {
      super.scene(scene, continue: userActivity)
    }
  }

  override func scene(
    _ scene: UIScene,
    openURLContexts URLContexts: Set<UIOpenURLContext>
  ) {
    let partition = WechatSceneURLRouter.partition(
      URLContexts.map { $0.url }
    ) { url in
      WechatAuthNativeBridge.shared.handleOpenURL(url)
    }
    let unconsumedContexts = Set(
      URLContexts.filter { partition.unconsumed.contains($0.url) }
    )
    if !unconsumedContexts.isEmpty {
      super.scene(scene, openURLContexts: unconsumedContexts)
    }
  }

  override func sceneDidDisconnect(_ scene: UIScene) {
    WechatAuthNativeBridge.shared.detach()
    super.sceneDidDisconnect(scene)
  }
}
