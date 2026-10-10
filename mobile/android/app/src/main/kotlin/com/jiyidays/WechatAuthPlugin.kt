package com.jiyidays

import android.app.Activity
import android.app.Application
import android.content.Context
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/** Provider-neutral MethodChannel bridge for the Android WeChat OpenSDK. */
class WechatAuthPlugin(
    private val injectedAdapter: WechatAuthProviderAdapter? = null,
) : FlutterPlugin, MethodChannel.MethodCallHandler, ActivityAware {
    companion object {
        const val CHANNEL = "cn.jiyidashi/wechat_auth"
    }

    private var channel: MethodChannel? = null
    private var adapter: WechatAuthProviderAdapter? = injectedAdapter
    private var activity: Activity? = null
    private var pending: PendingCall? = null
    private var initialized = false

    private data class PendingCall(
        val generation: Long,
        val result: MethodChannel.Result,
    )

    private var nextGeneration = 0L

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel = MethodChannel(binding.binaryMessenger, CHANNEL).also {
            it.setMethodCallHandler(this)
        }
        if (adapter == null) {
            adapter = WechatAuthNativeAdapter(
                context = binding.applicationContext,
                configuration = WechatAndroidConfiguration(
                    appId = BuildConfig.JIYI_WECHAT_APP_ID,
                    provider = BuildConfig.AUTH_WECHAT_PROVIDER,
                    liveEnabled = BuildConfig.JIYI_WECHAT_LIVE_ENABLED,
                ),
            )
        }
        (binding.applicationContext.applicationContext as? Application)?.let { application ->
            // Keep this hook explicit: the callback owner is the request-scoped
            // adapter, while lifecycle invalidation belongs to the plugin.
            application.registerActivityLifecycleCallbacks(lifecycleFence)
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        invalidatePending("ENGINE_DETACHED")
        adapter?.cancel { }
        (binding.applicationContext.applicationContext as? Application)?.let { application ->
            application.unregisterActivityLifecycleCallbacks(lifecycleFence)
        }
        channel?.setMethodCallHandler(null)
        channel = null
        adapter = injectedAdapter
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivityForConfigChanges() {
        invalidateForLifecycle("ACTIVITY_DETACHED")
        activity = null
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivity() {
        invalidateForLifecycle("ACTIVITY_DETACHED")
        activity = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "initialize" -> initialize(call, result)
            "checkAvailability" -> checkAvailability(result)
            "requestCredential" -> requestCredential(result)
            "cancel" -> cancel(result)
            "revokePrivacy" -> revokePrivacy(result)
            else -> result.notImplemented()
        }
    }

    private fun initialize(call: MethodCall, result: MethodChannel.Result) {
        val privacyGranted = call.argument<Boolean>("privacy_consent_granted") == true
        if (!privacyGranted) {
            revokePrivacy(result)
            return
        }
        if (pending != null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        beginAsync(result) { _, callback ->
            adapterOrUnavailable().initialize(true) { nativeResult ->
                if (callback.complete(nativeResult)) initialized = nativeResult.state == WechatAuthNativeState.AVAILABLE
            }
        }
    }

    private fun checkAvailability(result: MethodChannel.Result) {
        if (!initialized) {
            result.success(unavailable("NOT_INITIALIZED").toPlatformMap())
            return
        }
        if (pending != null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        beginAsync(result) { _, callback ->
            adapterOrUnavailable().checkAvailability { callback.complete(it) }
        }
    }

    private fun requestCredential(result: MethodChannel.Result) {
        if (!initialized) {
            result.success(unavailable("NOT_INITIALIZED").toPlatformMap())
            return
        }
        val requestActivity = activity
        if (requestActivity == null || requestActivity.isFinishing) {
            result.success(unavailable("ACTIVITY_UNAVAILABLE").toPlatformMap())
            return
        }
        if (pending != null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        beginAsync(result) { _, callback ->
            adapterOrUnavailable().requestCredential(requestActivity) { callback.complete(it) }
        }
    }

    private fun cancel(result: MethodChannel.Result) {
        invalidatePending("USER_CANCELLED")
        adapterOrUnavailable().cancel { nativeResult -> result.success(nativeResult.toPlatformMap()) }
    }

    private fun revokePrivacy(result: MethodChannel.Result) {
        invalidateForLifecycle("PRIVACY_REVOKED")
        initialized = false
        adapterOrUnavailable().revokePrivacy { nativeResult -> result.success(nativeResult.toPlatformMap()) }
    }

    private fun beginAsync(
        result: MethodChannel.Result,
        operation: (Long, CallbackFence) -> Unit,
    ) {
        val generation = synchronized(this) {
            if (pending != null) null else {
                nextGeneration += 1
                nextGeneration
            }
        } ?: run {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        synchronized(this) { pending = PendingCall(generation, result) }
        operation(generation, CallbackFence(generation) { nativeResult ->
            val pendingCall = synchronized(this) {
                val current = pending
                if (current?.generation == generation) pending = null
                current
            } ?: return@CallbackFence
            pendingCall.result.success(nativeResult.toPlatformMap())
        })
    }

    private fun invalidateForLifecycle(reason: String) {
        initialized = false
        invalidatePending(reason)
        adapterOrUnavailable().cancel { }
    }

    private fun invalidatePending(reason: String) {
        val pendingCall = synchronized(this) { pending.also { pending = null } }
        pendingCall?.result?.success(
            WechatAuthNativeResult(
                WechatAuthNativeState.CANCELLED,
                reason = reason,
            ).toPlatformMap(),
        )
    }

    private fun adapterOrUnavailable(): WechatAuthProviderAdapter =
        adapter ?: object : WechatAuthProviderAdapter {
            override fun initialize(privacyConsentGranted: Boolean, completion: (WechatAuthNativeResult) -> Unit) =
                completion(unavailable("NATIVE_UNAVAILABLE"))
            override fun checkAvailability(completion: (WechatAuthNativeResult) -> Unit) =
                completion(unavailable("NATIVE_UNAVAILABLE"))
            override fun requestCredential(activity: Activity, completion: (WechatAuthNativeResult) -> Unit) =
                completion(unavailable("NATIVE_UNAVAILABLE"))
            override fun cancel(completion: (WechatAuthNativeResult) -> Unit) =
                completion(WechatAuthNativeResult(WechatAuthNativeState.CANCELLED))
            override fun revokePrivacy(completion: (WechatAuthNativeResult) -> Unit) =
                completion(unavailable("PRIVACY_REVOKED"))
        }

    private fun unavailable(reason: String) =
        WechatAuthNativeResult(WechatAuthNativeState.UNAVAILABLE, reason = reason)

    private val lifecycleFence = object : Application.ActivityLifecycleCallbacks {
        private var started = 0

        override fun onActivityStarted(activity: Activity) {
            started += 1
        }

        override fun onActivityStopped(activity: Activity) {
            started = (started - 1).coerceAtLeast(0)
            if (started == 0 && !activity.isChangingConfigurations) {
                invalidateForLifecycle("APP_BACKGROUND")
            }
        }

        override fun onActivityCreated(activity: Activity, state: android.os.Bundle?) = Unit
        override fun onActivityResumed(activity: Activity) = Unit
        override fun onActivityPaused(activity: Activity) = Unit
        override fun onActivitySaveInstanceState(activity: Activity, state: android.os.Bundle) = Unit
        override fun onActivityDestroyed(activity: Activity) = Unit
    }

    private inner class CallbackFence(
        private val generation: Long,
        private val completion: (WechatAuthNativeResult) -> Unit,
    ) {
        private var completed = false

        @Synchronized
        fun complete(result: WechatAuthNativeResult): Boolean {
            if (completed) return false
            val current = synchronized(this@WechatAuthPlugin) { pending?.generation == generation }
            if (!current) return false
            completed = true
            completion(result)
            return true
        }
    }
}
