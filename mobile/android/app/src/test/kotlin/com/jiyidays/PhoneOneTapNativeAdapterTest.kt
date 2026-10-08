package com.jiyidays

import android.app.Activity
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneOneTapNativeAdapterTest {
    @Test
    fun failClosedAdapterRequiresPrivacyAndConfiguration() {
        val adapter = FailClosedPhoneOneTapProviderAdapter()
        var result: PhoneOneTapNativeResult? = null

        adapter.initialize(privacyConsentGranted = false) { result = it }
        assertEquals(PhoneOneTapNativeState.UNAVAILABLE, result?.state)
        assertEquals(
            "PRIVACY_NOT_ACCEPTED",
            result?.reason,
        )
        adapter.initialize(privacyConsentGranted = true) { result = it }
        assertEquals("PNVS_NOT_CONFIGURED", result?.reason)
        adapter.checkAvailability { result = it }
        assertEquals(PhoneOneTapNativeState.UNAVAILABLE, result?.state)
        adapter.requestLoginToken(activity = android.app.Activity()) { result = it }
        assertEquals(PhoneOneTapNativeState.UNAVAILABLE, result?.state)
    }

    @Test
    fun requestGateFencesRepeatedAndLateCallbacks() {
        val gate = PhoneOneTapRequestGate()
        val first = gate.begin()

        assertNotNull(first)
        assertNull(gate.begin())
        assertTrue(gate.isCurrent(first!!))
        assertFalse(gate.finish(first + 1))
        assertTrue(gate.hasActiveRequest())
        assertTrue(gate.finish(first))
        assertFalse(gate.hasActiveRequest())
        assertFalse(gate.finish(first))
    }

    @Test
    fun invalidationMakesLateCallbackStale() {
        val gate = PhoneOneTapRequestGate()
        val first = gate.begin()!!
        gate.invalidate()

        assertFalse(gate.isCurrent(first))
        assertFalse(gate.finish(first))
    }

    @Test
    fun asyncProviderCallbackCompletesOnceAndIgnoresLateCallback() {
        val gate = PhoneOneTapRequestGate()
        val generation = gate.begin()!!
        val values = mutableListOf<PhoneOneTapNativeResult>()
        val callback = PhoneOneTapCallbackFence(gate, generation) { values += it }
        val token = PhoneOneTapNativeResult(PhoneOneTapNativeState.TOKEN_ACQUIRED, "opaque")

        assertTrue(callback.complete(token))
        assertFalse(callback.complete(token))
        assertEquals(1, values.size)
        assertEquals(PhoneOneTapNativeState.TOKEN_ACQUIRED, values.single().state)
    }

    @Test
    fun privacyRevocationDoesNotInitializeFailClosedProvider() {
        val adapter = FailClosedPhoneOneTapProviderAdapter()
        var result: PhoneOneTapNativeResult? = null

        adapter.revokePrivacy { result = it }

        assertEquals(PhoneOneTapNativeState.UNAVAILABLE, result?.state)
        assertEquals("PRIVACY_REVOKED", result?.reason)
    }

    @Test
    fun platformResultDoesNotRequireProviderTypes() {
        val result = PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "opaque-token",
        )

        assertEquals("TOKEN_ACQUIRED", result.toPlatformMap()["state"])
        assertEquals("opaque-token", result.toPlatformMap()["login_token"])
    }

    @Test
    fun pluginUsesRequestScopedActivityAndFencesAsyncLifecycle() {
        val adapter = DelayedPhoneOneTapAdapter()
        val plugin = PhoneOneTapPlugin(adapter)
        val activityA = Activity()
        val activityB = Activity()

        val initialize = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to true)),
            initialize,
        )
        adapter.initializeCallback!!.invoke(
            PhoneOneTapNativeResult(PhoneOneTapNativeState.AVAILABLE),
        )
        val missingActivityRequest = RecordingResult()
        plugin.onMethodCall(MethodCall("requestLoginToken", null), missingActivityRequest)
        assertEquals("ACTIVITY_UNAVAILABLE", missingActivityRequest.value["reason"])
        assertTrue(adapter.requestedActivities.isEmpty())

        setPrivateActivity(plugin, activityA)

        val firstRequest = RecordingResult()
        plugin.onMethodCall(MethodCall("requestLoginToken", null), firstRequest)
        assertEquals(activityA, adapter.requestedActivities.single())
        val firstCallback = adapter.requestCallbacks.single()

        plugin.onDetachedFromActivity()
        assertEquals("ACTIVITY_DETACHED", firstRequest.value["reason"])
        firstCallback(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "late-a",
        ))
        assertEquals("CANCELLED", firstRequest.value["state"])

        setPrivateActivity(plugin, activityB)
        val reinitialize = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to true)),
            reinitialize,
        )
        adapter.initializeCallback!!.invoke(
            PhoneOneTapNativeResult(PhoneOneTapNativeState.AVAILABLE),
        )

        val secondRequest = RecordingResult()
        plugin.onMethodCall(MethodCall("requestLoginToken", null), secondRequest)
        assertEquals(activityB, adapter.requestedActivities.last())
        val secondCallback = adapter.requestCallbacks.last()
        secondCallback(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "token-b",
        ))
        secondCallback(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "duplicate-b",
        ))
        assertEquals("token-b", secondRequest.value["login_token"])
        assertEquals(1, secondRequest.callCount)

        val thirdRequest = RecordingResult()
        plugin.onMethodCall(MethodCall("requestLoginToken", null), thirdRequest)
        val thirdCallback = adapter.requestCallbacks.last()
        val privacyRevocation = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to false)),
            privacyRevocation,
        )
        thirdCallback(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "late-after-privacy-revocation",
        ))
        assertEquals("PRIVACY_REVOKED", thirdRequest.value["reason"])
        assertEquals("PRIVACY_REVOKED", privacyRevocation.value["reason"])
        assertEquals(1, thirdRequest.callCount)

        setPrivateActivity(plugin, activityB)
        val reinitializeAfterCancel = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to true)),
            reinitializeAfterCancel,
        )
        adapter.initializeCallback!!.invoke(
            PhoneOneTapNativeResult(PhoneOneTapNativeState.AVAILABLE),
        )
        val cancelRequest = RecordingResult()
        plugin.onMethodCall(MethodCall("requestLoginToken", null), cancelRequest)
        val cancelCallback = adapter.requestCallbacks.last()
        val cancelResult = RecordingResult()
        val cancelCountBefore = adapter.cancelCount
        plugin.onMethodCall(MethodCall("cancel", null), cancelResult)
        cancelCallback(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "late-after-cancel",
        ))
        assertEquals("USER_CANCELLED", cancelRequest.value["reason"])
        assertEquals("CANCELLED", cancelResult.value["state"])
        assertEquals(cancelCountBefore + 1, adapter.cancelCount)
        assertEquals(1, cancelRequest.callCount)
    }

    @Test
    fun applicationBackgroundFenceCancelsPluginRequestExactlyOnce() {
        val adapter = DelayedPhoneOneTapAdapter()
        val plugin = PhoneOneTapPlugin(adapter)
        val activity = Activity()
        setPrivateActivity(plugin, activity)
        val initialize = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to true)),
            initialize,
        )
        adapter.initializeCallback!!.invoke(
            PhoneOneTapNativeResult(PhoneOneTapNativeState.AVAILABLE),
        )
        val request = RecordingResult()
        plugin.onMethodCall(MethodCall("requestLoginToken", null), request)
        val providerCallback = adapter.requestCallbacks.single()

        val fence = PhoneOneTapApplicationLifecycleFence(
            onRealBackgrounded = { invokeLifecycleInvalidation(plugin) },
            scheduleBackgroundCheck = { _, task -> task() },
            isChangingConfigurations = { false },
        )
        fence.onActivityStarted(activity)
        fence.onActivityStopped(activity)
        providerCallback(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "late-background-token",
        ))

        assertEquals("APP_BACKGROUND", request.value["reason"])
        assertEquals("CANCELLED", request.value["state"])
        assertEquals(1, adapter.cancelCount)
        assertEquals(1, request.callCount)
    }

    private fun setPrivateActivity(plugin: PhoneOneTapPlugin, activity: Activity) {
        val field = PhoneOneTapPlugin::class.java.getDeclaredField("activity")
        field.isAccessible = true
        field.set(plugin, activity)
    }

    private fun invokeLifecycleInvalidation(plugin: PhoneOneTapPlugin) {
        val method = PhoneOneTapPlugin::class.java.getDeclaredMethod(
            "invalidateForLifecycle",
            String::class.java,
        )
        method.isAccessible = true
        method.invoke(plugin, "APP_BACKGROUND")
    }

    private class RecordingResult : MethodChannel.Result {
        val value = mutableMapOf<String, Any?>()
        var callCount = 0

        override fun success(result: Any?) {
            callCount += 1
            value.clear()
            if (result is Map<*, *>) {
                result.forEach { (key, item) -> value[key.toString()] = item }
            }
        }

        override fun error(errorCode: String, errorMessage: String?, errorDetails: Any?) = Unit
        override fun notImplemented() = Unit
    }

    private class DelayedPhoneOneTapAdapter : PhoneOneTapProviderAdapter {
        var initializeCallback: PhoneOneTapCompletion? = null
        val requestedActivities = mutableListOf<Activity>()
        val requestCallbacks = mutableListOf<PhoneOneTapCompletion>()
        var cancelCount = 0

        override fun initialize(privacyConsentGranted: Boolean, completion: PhoneOneTapCompletion) {
            initializeCallback = completion
        }

        override fun checkAvailability(completion: PhoneOneTapCompletion) = Unit
        override fun preLogin(completion: PhoneOneTapCompletion) = Unit

        override fun requestLoginToken(activity: Activity, completion: PhoneOneTapCompletion) {
            requestedActivities += activity
            requestCallbacks += completion
        }

        override fun cancel(completion: PhoneOneTapCompletion) {
            cancelCount += 1
            completion(PhoneOneTapNativeResult(PhoneOneTapNativeState.CANCELLED))
        }

        override fun revokePrivacy(completion: PhoneOneTapCompletion) {
            completion(PhoneOneTapNativeResult(
                PhoneOneTapNativeState.UNAVAILABLE,
                reason = "PRIVACY_REVOKED",
            ))
        }
    }
}
