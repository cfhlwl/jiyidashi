package com.jiyidays

import android.app.Activity
import android.app.Application
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WechatAuthNativeAdapterTest {
    private val configuration = WechatAndroidConfiguration(
        appId = "wx-test-only",
        provider = "wechat",
        liveEnabled = true,
    )

    @Test
    fun privacyAndMissingConfigurationFailClosedBeforeSdkAccess() {
        var factoryCalls = 0
        val adapter = WechatAuthNativeAdapter(
            context = Activity(),
            configuration = WechatAndroidConfiguration(
                appId = null,
                provider = "disabled",
                liveEnabled = false,
            ),
            sdkFactory = WechatOpenSdkFactory { _, _ ->
                factoryCalls += 1
                FakeWechatSdk()
            },
        )
        var result: WechatAuthNativeResult? = null

        adapter.initialize(privacyConsentGranted = false) { result = it }
        assertEquals(WechatAuthNativeState.UNAVAILABLE, result?.state)
        assertEquals("PRIVACY_REVOKED", result?.reason)
        adapter.initialize(privacyConsentGranted = true) { result = it }
        assertEquals("WECHAT_PROVIDER_DISABLED", result?.reason)
        assertEquals(0, factoryCalls)
    }

    @Test
    fun availabilityRequiresInstalledSupportedWechat() {
        val sdk = FakeWechatSdk(installed = false)
        val adapter = adapter(sdk)
        var result: WechatAuthNativeResult? = null
        adapter.initialize(true) { result = it }
        assertEquals(WechatAuthNativeState.AVAILABLE, result?.state)
        adapter.checkAvailability { result = it }
        assertEquals(WechatAuthNativeState.UNAVAILABLE, result?.state)
        assertEquals("WECHAT_NOT_INSTALLED", result?.reason)
    }

    @Test
    fun availabilityFailsClosedWhenWechatApiIsUnsupported() {
        val sdk = FakeWechatSdk(supported = false)
        val adapter = adapter(sdk)
        var result: WechatAuthNativeResult? = null
        adapter.initialize(true) { result = it }
        adapter.checkAvailability { result = it }
        assertEquals(WechatAuthNativeState.UNAVAILABLE, result?.state)
        assertEquals("WECHAT_API_UNSUPPORTED", result?.reason)
    }

    @Test
    fun matchingStateReturnsOpaqueCredentialOnlyOnce() {
        val sdk = FakeWechatSdk()
        val scheduler = TestScheduler()
        val adapter = adapter(sdk, scheduler)
        var result: WechatAuthNativeResult? = null
        adapter.initialize(true) { }
        adapter.requestCredential(TestActivity()) { result = it }
        val state = sdk.sentState
        assertNotNull(state)
        WechatAuthCallbackRegistry.dispatch(
            WechatSdkAuthResponse(0, code = "short-lived-code", state = state),
        )
        WechatAuthCallbackRegistry.dispatch(
            WechatSdkAuthResponse(0, code = "late-code", state = state),
        )
        assertEquals(WechatAuthNativeState.CREDENTIAL_ACQUIRED, result?.state)
        assertEquals("short-lived-code", result?.credential)
        assertFalse(scheduler.pending)
    }

    @Test
    fun stateMismatchFailsClosedAndNeverReturnsCode() {
        val sdk = FakeWechatSdk()
        val adapter = adapter(sdk)
        var result: WechatAuthNativeResult? = null
        adapter.initialize(true) { }
        adapter.requestCredential(TestActivity()) { result = it }
        WechatAuthCallbackRegistry.dispatch(
            WechatSdkAuthResponse(0, code = "must-not-cross-boundary", state = "spoofed"),
        )
        assertEquals(WechatAuthNativeState.PROVIDER_ERROR, result?.state)
        assertEquals("STATE_MISMATCH", result?.reason)
        assertNull(result?.credential)
    }

    @Test
    fun cancelAndTimeoutFenceLateCallbacks() {
        val sdk = FakeWechatSdk()
        val scheduler = TestScheduler()
        val adapter = adapter(sdk, scheduler)
        val results = mutableListOf<WechatAuthNativeResult>()
        adapter.initialize(true) { }
        adapter.requestCredential(TestActivity()) { results += it }
        adapter.cancel { results += it }
        WechatAuthCallbackRegistry.dispatch(
            WechatSdkAuthResponse(0, code = "late-after-cancel", state = sdk.sentState),
        )
        assertEquals(2, results.size)
        assertEquals(WechatAuthNativeState.CANCELLED, results[0].state)
        assertEquals(WechatAuthNativeState.CANCELLED, results[1].state)

        adapter.requestCredential(TestActivity()) { results += it }
        scheduler.fire()
        WechatAuthCallbackRegistry.dispatch(
            WechatSdkAuthResponse(0, code = "late-after-timeout", state = sdk.sentState),
        )
        assertEquals(WechatAuthNativeState.TIMEOUT, results.last().state)
        assertEquals(3, results.size)
    }

    @Test
    fun pluginChannelFencesRepeatedAndLateCredentialCallbacks() {
        val adapter = DelayedAdapter()
        val plugin = WechatAuthPlugin(adapter)
        setPrivateActivity(plugin, TestActivity())

        val initialize = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to true)),
            initialize,
        )
        assertEquals("AVAILABLE", initialize.value["state"])

        val request = RecordingResult()
        plugin.onMethodCall(MethodCall("requestCredential", null), request)
        val cancel = RecordingResult()
        plugin.onMethodCall(MethodCall("cancel", null), cancel)
        adapter.requestCallback?.invoke(
            WechatAuthNativeResult(
                WechatAuthNativeState.CREDENTIAL_ACQUIRED,
                credential = "late-code",
            ),
        )
        assertEquals("CANCELLED", request.value["state"])
        assertEquals("USER_CANCELLED", request.value["reason"])
        assertEquals(1, request.callCount)
        assertEquals("CANCELLED", cancel.value["state"])
        assertEquals(1, adapter.cancelCalls)
    }

    @Test
    fun applicationBackgroundCancelsPendingRequestAndForegroundRequiresReinitialize() {
        val adapter = DelayedAdapter()
        val plugin = WechatAuthPlugin(adapter)
        val activity = TestActivity()
        setPrivateActivity(plugin, activity)

        val initialize = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to true)),
            initialize,
        )
        val request = RecordingResult()
        plugin.onMethodCall(MethodCall("requestCredential", null), request)

        val callbacks = privateLifecycleCallbacks(plugin)
        callbacks.onActivityStarted(activity)
        callbacks.onActivityStopped(activity)

        assertEquals("CANCELLED", request.value["state"])
        assertEquals("APP_BACKGROUND", request.value["reason"])
        assertEquals(1, request.callCount)
        assertEquals(1, adapter.cancelCalls)

        adapter.requestCallback?.invoke(
            WechatAuthNativeResult(
                WechatAuthNativeState.CREDENTIAL_ACQUIRED,
                credential = "late-background-code",
            ),
        )
        assertEquals(1, request.callCount)

        val reinitialize = RecordingResult()
        plugin.onMethodCall(
            MethodCall("initialize", mapOf("privacy_consent_granted" to true)),
            reinitialize,
        )
        assertEquals("AVAILABLE", reinitialize.value["state"])

        val foregroundRequest = RecordingResult()
        plugin.onMethodCall(MethodCall("requestCredential", null), foregroundRequest)
        adapter.requestCallback?.invoke(
            WechatAuthNativeResult(
                WechatAuthNativeState.CREDENTIAL_ACQUIRED,
                credential = "foreground-code",
            ),
        )
        assertEquals("CREDENTIAL_ACQUIRED", foregroundRequest.value["state"])
        assertEquals("foreground-code", foregroundRequest.value["credential"])
        assertEquals(1, foregroundRequest.callCount)
    }

    private fun adapter(
        sdk: FakeWechatSdk,
        scheduler: TestScheduler = TestScheduler(),
    ) = WechatAuthNativeAdapter(
        context = Activity(),
        configuration = configuration,
        sdkFactory = WechatOpenSdkFactory { _, _ -> sdk },
        timeoutScheduler = scheduler,
    )

    private class FakeWechatSdk(
        private val installed: Boolean = true,
        private val supported: Boolean = true,
    ) : WechatOpenSdkClient {
        var sentState: String? = null

        override fun registerApp() = true
        override fun isWXAppInstalled() = installed
        override fun getWXAppSupportAPI() = if (supported) 1 else 0
        override fun sendAuthRequest(state: String): Boolean {
            sentState = state
            return true
        }
    }

    private class TestActivity : Activity() {
        override fun isFinishing(): Boolean = false
        override fun isChangingConfigurations(): Boolean = false
    }

    private class TestScheduler : WechatAuthTimeoutScheduler {
        private var task: (() -> Unit)? = null
        val pending: Boolean get() = task != null

        override fun schedule(delayMillis: Long, task: () -> Unit): () -> Unit {
            this.task = task
            return { this.task = null }
        }

        fun fire() {
            val current = task
            task = null
            current?.invoke()
        }
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

    private class DelayedAdapter : WechatAuthProviderAdapter {
        var requestCallback: ((WechatAuthNativeResult) -> Unit)? = null
        var cancelCalls = 0

        override fun initialize(
            privacyConsentGranted: Boolean,
            completion: (WechatAuthNativeResult) -> Unit,
        ) = completion(WechatAuthNativeResult(WechatAuthNativeState.AVAILABLE))

        override fun checkAvailability(completion: (WechatAuthNativeResult) -> Unit) =
            completion(WechatAuthNativeResult(WechatAuthNativeState.AVAILABLE))

        override fun requestCredential(
            activity: Activity,
            completion: (WechatAuthNativeResult) -> Unit,
        ) {
            requestCallback = completion
        }

        override fun cancel(completion: (WechatAuthNativeResult) -> Unit) {
            cancelCalls += 1
            completion(WechatAuthNativeResult(WechatAuthNativeState.CANCELLED))
        }

        override fun revokePrivacy(completion: (WechatAuthNativeResult) -> Unit) =
            completion(WechatAuthNativeResult(WechatAuthNativeState.UNAVAILABLE))
    }

    private fun setPrivateActivity(plugin: WechatAuthPlugin, activity: Activity) {
        val field = WechatAuthPlugin::class.java.getDeclaredField("activity")
        field.isAccessible = true
        field.set(plugin, activity)
    }

    private fun privateLifecycleCallbacks(
        plugin: WechatAuthPlugin,
    ): Application.ActivityLifecycleCallbacks {
        val field = WechatAuthPlugin::class.java.getDeclaredField("lifecycleFence")
        field.isAccessible = true
        return field.get(plugin) as Application.ActivityLifecycleCallbacks
    }
}
