package com.jiyidays

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class JiYiFirebaseMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        NotificationPushPlugin.publishToken(applicationContext, "FCM", token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data.toMutableMap()
        message.notification?.let { notification ->
            if (!data.containsKey("title")) {
                notification.title?.let { data["title"] = it }
            }
            if (!data.containsKey("body")) {
                notification.body?.let { data["body"] = it }
            }
        }
        NotificationPushRuntime.handleIncomingData(applicationContext, data)
    }
}
