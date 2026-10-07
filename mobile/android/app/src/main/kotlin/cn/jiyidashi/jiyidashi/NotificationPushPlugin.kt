package cn.jiyidashi.jiyidashi

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.PluginRegistry
import java.util.concurrent.CopyOnWriteArraySet

class NotificationPushPlugin :
    FlutterPlugin,
    MethodChannel.MethodCallHandler,
    ActivityAware,
    PluginRegistry.RequestPermissionsResultListener {

    companion object {
        private const val CHANNEL = "cn.jiyidashi/notifications"
        private const val REQUEST_NOTIFICATIONS = 7412
        private val channels = CopyOnWriteArraySet<MethodChannel>()
        private val mainHandler = Handler(Looper.getMainLooper())
        @Volatile private var applicationContext: Context? = null

        fun publishToken(context: Context, provider: String, token: String) {
            NotificationPushRuntime.storeToken(context, provider, token)
            emit(
                "token",
                NotificationPushRuntime.status(
                    context,
                    tokenOverride = token,
                    providerOverride = provider,
                ),
            )
        }

        fun publishNotification(payload: Map<String, Any>, eventId: String) {
            emit(
                "notification",
                mapOf("payload" to payload, "event_id" to eventId),
            )
        }

        fun publishTap(context: Context, payload: Map<String, Any>, eventId: String) {
            if (channels.isEmpty()) {
                NotificationPushRuntime.storePendingTap(context, payload, eventId)
                return
            }
            emit(
                "tap",
                mapOf("payload" to payload, "event_id" to eventId),
            )
        }

        private fun emit(method: String, arguments: Any?) {
            mainHandler.post {
                channels.forEach { channel ->
                    channel.invokeMethod(method, arguments)
                }
            }
        }
    }

    private lateinit var context: Context
    private lateinit var channel: MethodChannel
    private var activity: Activity? = null
    private var activityBinding: ActivityPluginBinding? = null
    private var pendingPermissionResult: MethodChannel.Result? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        applicationContext = context
        channel = MethodChannel(binding.binaryMessenger, CHANNEL)
        channel.setMethodCallHandler(this)
        channels.add(channel)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel.setMethodCallHandler(null)
        channels.remove(channel)
        if (channels.isEmpty()) applicationContext = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "ready" -> {
                NotificationPushRuntime.takePendingTap(context)?.let { (payload, eventId) ->
                    channel.invokeMethod(
                        "tap",
                        mapOf("payload" to payload, "event_id" to eventId),
                    )
                }
                result.success(null)
            }
            "status" -> result.success(NotificationPushRuntime.status(context))
            "requestPermission" -> requestPermission(result)
            "registerForPush" -> registerForPush(result)
            "unregisterFromPush" -> unregisterFromPush(result)
            else -> result.notImplemented()
        }
    }

    private fun requestPermission(result: MethodChannel.Result) {
        if (Build.VERSION.SDK_INT < 33 ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        ) {
            result.success(NotificationPushRuntime.status(context))
            return
        }
        val currentActivity = activity
        if (currentActivity == null) {
            result.error("push_activity_unavailable", "Push activity is unavailable", null)
            return
        }
        if (pendingPermissionResult != null) {
            result.error("push_permission_pending", "Push permission is already pending", null)
            return
        }
        NotificationPushRuntime.markPermissionRequested(context)
        pendingPermissionResult = result
        currentActivity.requestPermissions(
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            REQUEST_NOTIFICATIONS,
        )
    }

    private fun registerForPush(result: MethodChannel.Result) {
        if (NotificationPushRuntime.permission(context) != "authorized") {
            result.success(NotificationPushRuntime.status(context))
            return
        }
        if (NotificationPushRuntime.selectProvider(context) == null) {
            result.error(
                "push_provider_unavailable",
                "No reviewed Android push provider is available",
                null,
            )
            return
        }
        NotificationPushRuntime.obtainToken(context) { tokenResult ->
            mainHandler.post {
                tokenResult.fold(
                    onSuccess = { token ->
                        val provider = NotificationPushRuntime.selectProvider(context)
                        val status =
                            NotificationPushRuntime.status(
                                context,
                                tokenOverride = token,
                                providerOverride = provider,
                            )
                        result.success(status)
                        emit("token", status)
                    },
                    onFailure = {
                        result.error(
                            "push_provider_unavailable",
                            "Push provider token is unavailable",
                            null,
                        )
                    },
                )
            }
        }
    }

    private fun unregisterFromPush(result: MethodChannel.Result) {
        NotificationPushRuntime.deleteCurrentToken(context) { tokenResult ->
            mainHandler.post {
                tokenResult.fold(
                    onSuccess = {
                        result.success(null)
                        emit("token", NotificationPushRuntime.status(context))
                    },
                    onFailure = {
                        result.error(
                            "push_provider_unavailable",
                            "Push provider token retirement failed",
                            null,
                        )
                    },
                )
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ): Boolean {
        if (requestCode != REQUEST_NOTIFICATIONS) return false
        val pending = pendingPermissionResult
        pendingPermissionResult = null
        val status = NotificationPushRuntime.status(context)
        pending?.success(status)
        emit("permission", status)
        return true
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
        activityBinding = binding
        binding.addRequestPermissionsResultListener(this)
        NotificationPushRuntime.captureTapIntent(context, binding.activity.intent)
    }

    override fun onDetachedFromActivityForConfigChanges() {
        activityBinding?.removeRequestPermissionsResultListener(this)
        activityBinding = null
        activity = null
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        onAttachedToActivity(binding)
    }

    override fun onDetachedFromActivity() {
        activityBinding?.removeRequestPermissionsResultListener(this)
        activityBinding = null
        activity = null
    }
}
