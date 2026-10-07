package cn.jiyidashi.jiyidashi

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging
import com.huawei.hms.aaid.HmsInstanceId
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONObject

internal object NotificationPushRuntime {
    private const val PREFS = "jiyi_push_v1"
    private const val KEY_PROVIDER = "provider"
    private const val KEY_TOKEN = "token"
    private const val KEY_PERMISSION_REQUESTED = "permission_requested"
    private const val KEY_PENDING_TAP = "pending_tap"
    private const val CHANNEL_ID = "jiyi_general"
    private const val EXTRA_VERSION = "jiyi_push_version"
    private const val EXTRA_DESTINATION = "jiyi_push_destination"
    private const val EXTRA_RESOURCE_ID = "jiyi_push_resource_id"
    private const val EXTRA_EVENT_ID = "jiyi_push_event_id"
    private val allowedDestinations =
        setOf("HOME", "REMINDER", "MEMORY", "APP_UPDATE", "FAMILY", "EXPORT")
    private val executor = Executors.newSingleThreadExecutor()
    private val notificationIds = AtomicInteger(4000)

    data class CanonicalMessage(
        val payload: Map<String, Any>,
        val title: String,
        val body: String,
        val eventId: String = UUID.randomUUID().toString(),
    )

    fun status(context: Context): Map<String, Any?> {
        val selected = selectProvider(context)
        val prefs = prefs(context)
        val storedProvider = prefs.getString(KEY_PROVIDER, null)
        val storedToken = prefs.getString(KEY_TOKEN, null)
        val token =
            if (selected != null && selected == storedProvider && !storedToken.isNullOrBlank()) {
                storedToken
            } else {
                null
            }
        return mapOf(
            "supported" to true,
            "platform" to "ANDROID",
            "permission" to permission(context),
            "provider" to selected,
            "token" to token,
            "app_version" to BuildConfig.VERSION_NAME,
            "os_version" to Build.VERSION.RELEASE,
        )
    }

    fun markPermissionRequested(context: Context) {
        prefs(context).edit().putBoolean(KEY_PERMISSION_REQUESTED, true).apply()
    }

    fun permission(context: Context): String {
        if (Build.VERSION.SDK_INT < 33) return "authorized"
        if (context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            return "authorized"
        }
        return if (prefs(context).getBoolean(KEY_PERMISSION_REQUESTED, false)) {
            "denied"
        } else {
            "notDetermined"
        }
    }

    fun selectProvider(context: Context): String? {
        val hmsConfigured = BuildConfig.JIYI_HMS_APP_ID.isNotBlank()
        val fcmConfigured =
            BuildConfig.JIYI_FCM_PROJECT_ID.isNotBlank() &&
                BuildConfig.JIYI_FCM_APP_ID.isNotBlank() &&
                BuildConfig.JIYI_FCM_API_KEY.isNotBlank() &&
                BuildConfig.JIYI_FCM_SENDER_ID.isNotBlank()
        return NotificationProviderSelector.select(
            hmsConfigured = hmsConfigured,
            hmsAvailable = packageInstalled(context, "com.huawei.hwid"),
            fcmConfigured = fcmConfigured,
            gmsAvailable = packageInstalled(context, "com.google.android.gms"),
        )
    }

    fun obtainToken(
        context: Context,
        callback: (Result<String>) -> Unit,
    ) {
        when (val provider = selectProvider(context)) {
            "FCM" -> obtainFcmToken(context, callback)
            "HMS" -> obtainHmsToken(context, callback)
            else -> callback(Result.failure(IllegalStateException("provider_unavailable")))
        }
    }

    fun deleteCurrentToken(
        context: Context,
        callback: (Result<Unit>) -> Unit,
    ) {
        val prefs = prefs(context)
        val provider = prefs.getString(KEY_PROVIDER, null)
        when (provider) {
            "FCM" -> {
                ensureFirebase(context)
                FirebaseMessaging.getInstance().deleteToken().addOnCompleteListener { task ->
                    if (task.isSuccessful) {
                        clearToken(context)
                        callback(Result.success(Unit))
                    } else {
                        callback(Result.failure(task.exception ?: IllegalStateException("fcm_delete")))
                    }
                }
            }
            "HMS" -> {
                executor.execute {
                    try {
                        HmsInstanceId.getInstance(context)
                            .deleteToken(BuildConfig.JIYI_HMS_APP_ID, "HCM")
                        clearToken(context)
                        callback(Result.success(Unit))
                    } catch (error: Throwable) {
                        callback(Result.failure(error))
                    }
                }
            }
            else -> {
                clearToken(context)
                callback(Result.success(Unit))
            }
        }
    }

    fun storeToken(context: Context, provider: String, token: String) {
        if (provider !in setOf("FCM", "HMS") || token.isBlank()) return
        prefs(context)
            .edit()
            .putString(KEY_PROVIDER, provider)
            .putString(KEY_TOKEN, token)
            .apply()
    }

    fun clearToken(context: Context) {
        prefs(context)
            .edit()
            .remove(KEY_PROVIDER)
            .remove(KEY_TOKEN)
            .apply()
    }

    fun parseCanonicalMessage(data: Map<String, String>): CanonicalMessage? {
        if (data["version"]?.toIntOrNull() != 1) return null
        var destination = data["destination"]?.uppercase() ?: "HOME"
        if (destination !in allowedDestinations) destination = "HOME"

        var resourceId = data["resource_id"]?.takeIf { it.isNotBlank() }
        if (resourceId != null) {
            resourceId =
                try {
                    UUID.fromString(resourceId).toString()
                } catch (_: IllegalArgumentException) {
                    destination = "HOME"
                    null
                }
        }
        if (destination == "MEMORY" && resourceId == null) {
            destination = "HOME"
        }

        val payload = mutableMapOf<String, Any>(
            "version" to 1,
            "destination" to destination,
        )
        if (resourceId != null) payload["resource_id"] = resourceId

        return CanonicalMessage(
            payload = payload,
            title = data["title"]?.take(160)?.ifBlank { "迹忆" } ?: "迹忆",
            body = data["body"]?.take(1000).orEmpty(),
        )
    }

    fun handleIncomingData(context: Context, data: Map<String, String>) {
        val message = parseCanonicalMessage(data) ?: return
        NotificationPushPlugin.publishNotification(message.payload, message.eventId)
        if (permission(context) == "authorized") {
            postSystemNotification(context, message)
        }
    }

    fun captureTapIntent(context: Context, intent: Intent?) {
        intent ?: return
        if (intent.getIntExtra(EXTRA_VERSION, 0) != 1) return
        var destination = intent.getStringExtra(EXTRA_DESTINATION)?.uppercase() ?: "HOME"
        if (destination !in allowedDestinations) destination = "HOME"
        var resourceId = intent.getStringExtra(EXTRA_RESOURCE_ID)
        if (!resourceId.isNullOrBlank()) {
            resourceId =
                try {
                    UUID.fromString(resourceId).toString()
                } catch (_: IllegalArgumentException) {
                    destination = "HOME"
                    null
                }
        }
        if (destination == "MEMORY" && resourceId.isNullOrBlank()) {
            destination = "HOME"
        }
        val payload = mutableMapOf<String, Any>(
            "version" to 1,
            "destination" to destination,
        )
        if (!resourceId.isNullOrBlank()) payload["resource_id"] = resourceId
        val eventId =
            intent.getStringExtra(EXTRA_EVENT_ID)?.takeIf { it.isNotBlank() }
                ?: UUID.randomUUID().toString()
        NotificationPushPlugin.publishTap(context, payload, eventId)
        intent.removeExtra(EXTRA_VERSION)
        intent.removeExtra(EXTRA_DESTINATION)
        intent.removeExtra(EXTRA_RESOURCE_ID)
        intent.removeExtra(EXTRA_EVENT_ID)
    }

    fun storePendingTap(
        context: Context,
        payload: Map<String, Any>,
        eventId: String,
    ) {
        val body =
            JSONObject().apply {
                put("event_id", eventId)
                put("version", payload["version"])
                put("destination", payload["destination"])
                payload["resource_id"]?.let { put("resource_id", it) }
            }
        prefs(context).edit().putString(KEY_PENDING_TAP, body.toString()).apply()
    }

    fun takePendingTap(context: Context): Pair<Map<String, Any>, String>? {
        val raw = prefs(context).getString(KEY_PENDING_TAP, null) ?: return null
        prefs(context).edit().remove(KEY_PENDING_TAP).apply()
        return try {
            val body = JSONObject(raw)
            val payload = mutableMapOf<String, Any>(
                "version" to body.optInt("version", 0),
                "destination" to body.optString("destination", "HOME"),
            )
            if (body.has("resource_id")) {
                payload["resource_id"] = body.getString("resource_id")
            }
            payload to body.getString("event_id")
        } catch (_: Throwable) {
            null
        }
    }

    private fun obtainFcmToken(
        context: Context,
        callback: (Result<String>) -> Unit,
    ) {
        try {
            ensureFirebase(context)
            FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
                val token = task.result
                if (task.isSuccessful && !token.isNullOrBlank()) {
                    storeToken(context, "FCM", token)
                    callback(Result.success(token))
                } else {
                    callback(Result.failure(task.exception ?: IllegalStateException("fcm_token")))
                }
            }
        } catch (error: Throwable) {
            callback(Result.failure(error))
        }
    }

    private fun obtainHmsToken(
        context: Context,
        callback: (Result<String>) -> Unit,
    ) {
        executor.execute {
            try {
                val token =
                    HmsInstanceId.getInstance(context)
                        .getToken(BuildConfig.JIYI_HMS_APP_ID, "HCM")
                if (token.isBlank()) throw IllegalStateException("hms_token_empty")
                storeToken(context, "HMS", token)
                callback(Result.success(token))
            } catch (error: Throwable) {
                callback(Result.failure(error))
            }
        }
    }

    private fun ensureFirebase(context: Context) {
        if (FirebaseApp.getApps(context).any { it.name == FirebaseApp.DEFAULT_APP_NAME }) {
            return
        }
        val options =
            FirebaseOptions.Builder()
                .setProjectId(BuildConfig.JIYI_FCM_PROJECT_ID)
                .setApplicationId(BuildConfig.JIYI_FCM_APP_ID)
                .setApiKey(BuildConfig.JIYI_FCM_API_KEY)
                .setGcmSenderId(BuildConfig.JIYI_FCM_SENDER_ID)
                .build()
        FirebaseApp.initializeApp(context, options)
            ?: throw IllegalStateException("firebase_init_failed")
    }

    private fun postSystemNotification(context: Context, message: CanonicalMessage) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "迹忆通知",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ),
            )
        }

        val intent =
            Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                putExtra(EXTRA_VERSION, 1)
                putExtra(
                    EXTRA_DESTINATION,
                    message.payload["destination"]?.toString() ?: "HOME",
                )
                message.payload["resource_id"]?.let {
                    putExtra(EXTRA_RESOURCE_ID, it.toString())
                }
                putExtra(EXTRA_EVENT_ID, message.eventId)
            }
        val pendingIntent =
            PendingIntent.getActivity(
                context,
                message.eventId.hashCode(),
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )

        val builder =
            if (Build.VERSION.SDK_INT >= 26) {
                Notification.Builder(context, CHANNEL_ID)
            } else {
                @Suppress("DEPRECATION")
                Notification.Builder(context)
            }
        builder
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(message.title)
            .setContentText(message.body)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
        manager.notify(notificationIds.incrementAndGet(), builder.build())
    }

    private fun packageInstalled(context: Context, packageName: String): Boolean {
        return try {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(packageName, 0)
            true
        } catch (_: PackageManager.NameNotFoundException) {
            false
        }
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
