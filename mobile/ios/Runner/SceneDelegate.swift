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
    _ = WechatAuthNativeBridge.shared.handleOpenUniversalLink(userActivity)
    super.scene(scene, continue: userActivity)
  }

  override func scene(
    _ scene: UIScene,
    openURLContexts URLContexts: Set<UIOpenURLContext>
  ) {
    for context in URLContexts {
      _ = WechatAuthNativeBridge.shared.handleOpenURL(context.url)
    }
    super.scene(scene, openURLContexts: URLContexts)
  }
}
