package com.jiyidays

import android.app.Activity
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

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
    private var activity: Activity? = null
    private var initialized = false

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel = MethodChannel(binding.binaryMessenger, CHANNEL)
        channel.setMethodCallHandler(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        requestGate.invalidate()
        adapter.cancel()
        initialized = false
        channel.setMethodCallHandler(null)
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivityForConfigChanges() {
        detachActivity()
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        onAttachedToActivity(binding)
    }

    override fun onDetachedFromActivity() {
        detachActivity()
    }

    private fun detachActivity() {
        activity = null
        requestGate.invalidate()
        adapter.cancel()
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "initialize" -> initialize(call, result)
            "checkAvailability" -> result.success(availability().toPlatformMap())
            "preLogin" -> result.success(preLogin().toPlatformMap())
            "requestLoginToken" -> requestLoginToken(result)
            "cancel" -> {
                requestGate.invalidate()
                result.success(adapter.cancel().toPlatformMap())
            }
            else -> result.notImplemented()
        }
    }

    private fun initialize(call: MethodCall, result: MethodChannel.Result) {
        val privacyConsentGranted = call.argument<Boolean>("privacy_consent_granted")
        if (privacyConsentGranted != true) {
            initialized = false
            result.success(
                PhoneOneTapNativeResult(
                    PhoneOneTapNativeState.UNAVAILABLE,
                    reason = "PRIVACY_NOT_ACCEPTED",
                ).toPlatformMap(),
            )
            return
        }
        val initializedResult = adapter.initialize(privacyConsentGranted = true)
        initialized = initializedResult.state != PhoneOneTapNativeState.UNAVAILABLE
        result.success(initializedResult.toPlatformMap())
    }

    private fun availability(): PhoneOneTapNativeResult {
        if (!initialized) {
            return PhoneOneTapNativeResult(
                PhoneOneTapNativeState.UNAVAILABLE,
                reason = "NOT_INITIALIZED",
            )
        }
        if (requestGate.hasActiveRequest()) {
            return PhoneOneTapNativeResult(
                PhoneOneTapNativeState.UNAVAILABLE,
                reason = "REQUEST_IN_PROGRESS",
            )
        }
        return adapter.checkAvailability()
    }

    private fun preLogin(): PhoneOneTapNativeResult {
        if (!initialized) return unavailable("NOT_INITIALIZED")
        if (requestGate.hasActiveRequest()) return unavailable("REQUEST_IN_PROGRESS")
        return adapter.preLogin()
    }

    private fun requestLoginToken(result: MethodChannel.Result) {
        if (!initialized) {
            result.success(unavailable("NOT_INITIALIZED").toPlatformMap())
            return
        }
        val generation = requestGate.begin()
        if (generation == null) {
            result.success(unavailable("REQUEST_IN_PROGRESS").toPlatformMap())
            return
        }
        val response = adapter.requestLoginToken(activityAvailable = activity != null)
        if (requestGate.isCurrent(generation)) {
            requestGate.finish(generation)
            result.success(response.toPlatformMap())
        }
    }

    private fun unavailable(reason: String) =
        PhoneOneTapNativeResult(PhoneOneTapNativeState.UNAVAILABLE, reason = reason)
}
