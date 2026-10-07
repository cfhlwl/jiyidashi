package com.jiyidays

import com.huawei.hms.push.HmsMessageService
import com.huawei.hms.push.RemoteMessage
import org.json.JSONObject

class JiYiHmsMessageService : HmsMessageService() {
    override fun onNewToken(token: String) {
        NotificationPushPlugin.publishToken(applicationContext, "HMS", token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = mutableMapOf<String, String>()
        val raw = message.data
        if (!raw.isNullOrBlank()) {
            try {
                val json = JSONObject(raw)
                json.keys().forEach { key ->
                    data[key] = json.optString(key)
                }
            } catch (_: Throwable) {
                return
            }
        }
        message.notification?.let { notification ->
            if (!data.containsKey("title")) {
                data["title"] = notification.title.orEmpty()
            }
            if (!data.containsKey("body")) {
                data["body"] = notification.body.orEmpty()
            }
        }
        NotificationPushRuntime.handleIncomingData(applicationContext, data)
    }
}
