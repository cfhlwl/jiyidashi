import Flutter
import UIKit
import UserNotifications

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
    var handled = false
    for context in URLContexts {
      handled = WechatAuthNativeBridge.shared.handleOpenURL(context.url) || handled
    }
    if !handled {
      super.scene(scene, openURLContexts: URLContexts)
    }
  }

  override func sceneDidDisconnect(_ scene: UIScene) {
    WechatAuthNativeBridge.shared.detach()
    super.sceneDidDisconnect(scene)
  }
}
