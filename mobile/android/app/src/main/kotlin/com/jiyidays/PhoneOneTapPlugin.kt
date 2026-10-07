package com.jiyidays

import android.app.Activity
import android.app.Application
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.atomic.AtomicBoolean

/** Provider-neutral Flutter channel; Alibaba DTOs never cross this boundary. */
class PhoneOneTapPlugin(
    private val adapter: PhoneOneTapProviderAdapter =
        FailClosedPhoneOneTapProviderAdapter(),
) : FlutterPlugin, MethodChannel.MethodCallHandler, ActivityAware {
    companion object {
        const val CHANNEL = "cn.jiyidashi/phone_one_tap"
    }

    private lateinit var channel: MethodChannel
    private val requestGate = PhoneOneTapRequestGate()
    private var pending: PendingCall? = null
    private var lifecycleFence: PhoneOneTapApplicationLifecycleFence? = null
    private var application: Application? = null
    private var activity: Activity? = null
    private var initialized = false

    private data class PendingCall(
        val generation: Long,
        val result: MethodChannel.Result,
    )

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel = MethodChannel(binding.binaryMessenger, CHANNEL)
        channel.setMethodCallHandler(this)
        val app = binding.applicationContext.applicationContext as? Application
        application = app
        if (app != null) {
            lifecycleFence = PhoneOneTapApplicationLifecycleFence(
                onRealBackgrounded = { invalidateForLifecycle("APP_BACKGROUND") },
            ).also { it.register(app) }
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        invalidateForLifecycle("ENGINE_DETACHED")
        lifecycleFence?.let { fence -> application?.let(fence::unregister) }
        lifecycleFence = null
        application = null
        channel.setMethodCallHandler(null)
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivityForConfigChanges() {
        invalidateForLifecycle("ACTIVITY_DETACHED")
        activity = null
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        onAttachedToActivity(binding)
    }

    override fun onDetachedFromActivity() {
        invalidateForLifecycle("ACTIVITY_DETACHED")
        activity = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "initialize" -> initialize(call, result)
            "checkAvailability" -> checkAvailability(result)
            "preLogin" -> preLogin(result)
            "requestLoginToken" -> requestLoginToken(result)
            "cancel" -> cancel(result)
            else -> result.notImplemented()
        }
    }

    private fun initialize(call: MethodCall, result: MethodChannel.Result) {
        val privacyConsentGranted = call.argument<Boolean>("privacy_consent_granted") == true
        if (!privacyConsentGranted) {
            revokePrivacy(result)
            return
        }
        if (pending != null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        beginAsync(result) { _, callback ->
            adapter.initialize(true) { nativeResult ->
                if (callback.complete(nativeResult)) {
                    initialized = nativeResult.state != PhoneOneTapNativeState.UNAVAILABLE
                }
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
        beginAsync(result) { _, callback -> adapter.checkAvailability { callback.complete(it) } }
    }

    private fun preLogin(result: MethodChannel.Result) {
        if (!initialized) {
            result.success(unavailable("NOT_INITIALIZED").toPlatformMap())
            return
        }
        if (pending != null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        beginAsync(result) { _, callback -> adapter.preLogin { callback.complete(it) } }
    }

    private fun requestLoginToken(result: MethodChannel.Result) {
        if (!initialized) {
            result.success(unavailable("NOT_INITIALIZED").toPlatformMap())
            return
        }
        if (activity == null) {
            result.success(unavailable("ACTIVITY_UNAVAILABLE").toPlatformMap())
            return
        }
        if (pending != null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        beginAsync(result) { _, callback ->
            adapter.requestLoginToken(activityAvailable = true) { callback.complete(it) }
        }
    }

    private fun cancel(result: MethodChannel.Result) {
        invalidatePending("USER_CANCELLED")
        completeAdapterOperationOnce(result) { callback -> adapter.cancel(callback) }
    }

    private fun revokePrivacy(result: MethodChannel.Result) {
        invalidatePending("PRIVACY_REVOKED")
        initialized = false
        completeAdapterOperationOnce(result) { callback -> adapter.revokePrivacy(callback) }
    }

    private fun beginAsync(
        result: MethodChannel.Result,
        operation: (Long, PhoneOneTapCallbackFence) -> Unit,
    ) {
        val generation = requestGate.begin()
        if (generation == null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        synchronized(this) {
            pending = PendingCall(generation, result)
        }
        val callback = PhoneOneTapCallbackFence(requestGate, generation) { nativeResult ->
            val pendingCall = synchronized(this) {
                val current = pending
                if (current?.generation == generation) pending = null
                current
            } ?: return@PhoneOneTapCallbackFence
            pendingCall.result.success(nativeResult.toPlatformMap())
        }
        operation(generation, callback)
    }

    private fun invalidateForLifecycle(reason: String) {
        invalidatePending(reason)
        initialized = false
        adapter.cancel { }
    }

    private fun invalidatePending(reason: String) {
        val pendingCall = synchronized(this) {
            requestGate.invalidate()
            val current = pending
            pending = null
            current
        }
        pendingCall?.result?.success(
            PhoneOneTapNativeResult(
                PhoneOneTapNativeState.CANCELLED,
                reason = reason,
            ).toPlatformMap(),
        )
    }

    private fun completeAdapterOperationOnce(
        result: MethodChannel.Result,
        operation: (PhoneOneTapCompletion) -> Unit,
    ) {
        val completed = AtomicBoolean(false)
        operation { nativeResult ->
            if (completed.compareAndSet(false, true)) {
                result.success(nativeResult.toPlatformMap())
            }
        }
    }

    private fun unavailable(reason: String) =
        PhoneOneTapNativeResult(PhoneOneTapNativeState.UNAVAILABLE, reason = reason)
}
