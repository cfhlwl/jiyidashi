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
  }
}
