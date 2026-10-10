package com.jiyidays

import android.app.Activity
import android.content.Context
import android.os.Handler
import android.os.Looper
import com.tencent.mm.opensdk.modelmsg.SendAuth
import com.tencent.mm.opensdk.openapi.IWXAPI
import com.tencent.mm.opensdk.openapi.WXAPIFactory
import java.util.UUID

enum class WechatAuthNativeState {
    AVAILABLE,
    UNAVAILABLE,
    CANCELLED,
    TIMEOUT,
    PROVIDER_ERROR,
    CREDENTIAL_ACQUIRED,
}

data class WechatAuthNativeResult(
    val state: WechatAuthNativeState,
    val credential: String? = null,
    val reason: String? = null,
) {
    fun toPlatformMap(): Map<String, Any> = buildMap {
        put("state", state.name)
        if (credential != null) put("credential", credential)
        if (reason != null) put("reason", reason)
    }

    override fun toString(): String =
        "WechatAuthNativeResult(state=$state, reason=${reason ?: "none"})"
}

data class WechatAndroidConfiguration(
    val appId: String?,
    val provider: String,
    val liveEnabled: Boolean,
) {
    fun missingConfigurationReason(): String = when {
        !liveEnabled -> "WECHAT_PROVIDER_DISABLED"
        !provider.equals("wechat", ignoreCase = true) -> "WECHAT_PROVIDER_DISABLED"
        appId.isNullOrBlank() -> "WECHAT_APP_ID_MISSING"
        else -> "WECHAT_NOT_CONFIGURED"
    }

    val isConfigured: Boolean
        get() = liveEnabled &&
            provider.equals("wechat", ignoreCase = true) &&
            !appId.isNullOrBlank()
}

interface WechatAuthProviderAdapter {
    fun initialize(privacyConsentGranted: Boolean, completion: (WechatAuthNativeResult) -> Unit)
    fun checkAvailability(completion: (WechatAuthNativeResult) -> Unit)
    fun requestCredential(activity: Activity, completion: (WechatAuthNativeResult) -> Unit)
    fun cancel(completion: (WechatAuthNativeResult) -> Unit)
    fun revokePrivacy(completion: (WechatAuthNativeResult) -> Unit)
}

interface WechatOpenSdkClient {
    fun registerApp(): Boolean
    fun isWXAppInstalled(): Boolean
    fun getWXAppSupportAPI(): Int
    fun sendAuthRequest(state: String): Boolean
}

fun interface WechatOpenSdkFactory {
    fun create(context: Context, appId: String): WechatOpenSdkClient
}

fun interface WechatAuthTimeoutScheduler {
    fun schedule(delayMillis: Long, task: () -> Unit): () -> Unit
}

private fun scheduleWechatTimeout(delayMillis: Long, task: () -> Unit): () -> Unit {
    val handler = Handler(Looper.getMainLooper())
    val runnable = Runnable { task() }
    handler.postDelayed(runnable, delayMillis)
    return { handler.removeCallbacks(runnable) }
}

data class WechatSdkAuthResponse(
    val errorCode: Int,
    val code: String? = null,
    val state: String? = null,
) {
    override fun toString(): String =
        "WechatSdkAuthResponse(errorCode=$errorCode, statePresent=${!state.isNullOrBlank()})"
}

/**
 * The callback Activity is only a transport endpoint. It never owns a
 * controller or a login result; the request-scoped adapter owns that state.
 */
object WechatAuthCallbackRegistry {
    private data class Registration(
        val generation: Long,
        val callback: (WechatSdkAuthResponse) -> Unit,
    )

    private var registration: Registration? = null

    @Synchronized
    fun install(generation: Long, callback: (WechatSdkAuthResponse) -> Unit): Boolean {
        if (registration != null) return false
        registration = Registration(generation, callback)
        return true
    }

    @Synchronized
    fun clear(generation: Long) {
        if (registration?.generation == generation) registration = null
    }

    fun dispatch(response: WechatSdkAuthResponse) {
        val callback = synchronized(this) { registration?.callback }
        callback?.invoke(response)
    }
}

/**
 * Real Android OpenSDK adapter. The only value returned to Flutter is the
 * short-lived authorization code; it is not logged, persisted, or cached.
 */
class WechatAuthNativeAdapter(
    private val context: Context,
    private val configuration: WechatAndroidConfiguration,
    private val sdkFactory: WechatOpenSdkFactory = WechatOpenSdkFactory { appContext, appId ->
        WechatOpenSdkClientImpl(WXAPIFactory.createWXAPI(appContext, appId, true), appId)
    },
    private val timeoutScheduler: WechatAuthTimeoutScheduler =
        WechatAuthTimeoutScheduler(::scheduleWechatTimeout),
    private val timeoutMillis: Long = REQUEST_TIMEOUT_MILLIS,
) : WechatAuthProviderAdapter {
    companion object {
        const val REQUEST_TIMEOUT_MILLIS = 60_000L
        const val ERR_OK = 0
        const val ERR_USER_CANCEL = -2
        const val ERR_AUTH_DENIED = -4
    }

    private data class PendingRequest(
        val generation: Long,
        val state: String,
        val completion: (WechatAuthNativeResult) -> Unit,
        val cancelTimeout: () -> Unit,
    )

    private val lock = Any()
    private var nextGeneration = 0L
    private var pending: PendingRequest? = null
    private var sdk: WechatOpenSdkClient? = null
    private var privacyGranted = false
    private var initialized = false

    override fun initialize(
        privacyConsentGranted: Boolean,
        completion: (WechatAuthNativeResult) -> Unit,
    ) {
        if (!privacyConsentGranted) {
            revokePrivacy(completion)
            return
        }
        if (!configuration.isConfigured) {
            synchronized(lock) {
                privacyGranted = true
                initialized = false
                sdk = null
            }
            completion(unavailable(configuration.missingConfigurationReason()))
            return
        }
        try {
            val created = sdkFactory.create(context, configuration.appId!!)
            val registered = created.registerApp()
            synchronized(lock) {
                privacyGranted = true
                initialized = registered
                sdk = if (registered) created else null
            }
            completion(
                if (registered) {
                    WechatAuthNativeResult(WechatAuthNativeState.AVAILABLE)
                } else {
                    unavailable("SDK_REGISTER_FAILED")
                },
            )
        } catch (_: Throwable) {
            synchronized(lock) {
                privacyGranted = true
                initialized = false
                sdk = null
            }
            completion(unavailable("SDK_INITIALIZATION_FAILED"))
        }
    }

    override fun checkAvailability(completion: (WechatAuthNativeResult) -> Unit) {
        val client = synchronized(lock) {
            if (!privacyGranted || !initialized) null else sdk
        }
        if (client == null) {
            completion(unavailable(if (!privacyGranted) "PRIVACY_NOT_ACCEPTED" else "NOT_INITIALIZED"))
            return
        }
        try {
            if (!client.isWXAppInstalled()) {
                completion(unavailable("WECHAT_NOT_INSTALLED"))
            } else if (client.getWXAppSupportAPI() <= 0) {
                completion(unavailable("WECHAT_API_UNSUPPORTED"))
            } else {
                completion(WechatAuthNativeResult(WechatAuthNativeState.AVAILABLE))
            }
        } catch (_: Throwable) {
            completion(unavailable("SDK_AVAILABILITY_FAILED"))
        }
    }

    override fun requestCredential(
        activity: Activity,
        completion: (WechatAuthNativeResult) -> Unit,
    ) {
        val client = synchronized(lock) {
            if (!privacyGranted || !initialized || activity.isFinishing) null else sdk
        }
        if (client == null) {
            completion(unavailable(if (!privacyGranted) "PRIVACY_NOT_ACCEPTED" else "NOT_AVAILABLE"))
            return
        }
        val generation = synchronized(lock) {
            if (pending != null) return@synchronized null
            nextGeneration += 1
            nextGeneration
        }
        if (generation == null) {
            completion(unavailable("REQUEST_IN_PROGRESS"))
            return
        }
        val state = UUID.randomUUID().toString()
        val cancelTimeout = timeoutScheduler.schedule(timeoutMillis) {
            complete(generation, WechatAuthNativeResult(WechatAuthNativeState.TIMEOUT))
        }
        synchronized(lock) {
            pending = PendingRequest(generation, state, completion, cancelTimeout)
        }
        val installed = WechatAuthCallbackRegistry.install(generation) { response ->
            when (response.errorCode) {
                ERR_USER_CANCEL -> complete(
                    generation,
                    WechatAuthNativeResult(
                        WechatAuthNativeState.CANCELLED,
                        reason = "USER_CANCELLED",
                    ),
                )
                ERR_AUTH_DENIED -> complete(
                    generation,
                    WechatAuthNativeResult(
                        WechatAuthNativeState.PROVIDER_ERROR,
                        reason = "AUTH_DENIED",
                    ),
                )
                ERR_OK -> {
                    if (response.state != state) {
                        complete(
                            generation,
                            WechatAuthNativeResult(
                                WechatAuthNativeState.PROVIDER_ERROR,
                                reason = "STATE_MISMATCH",
                            ),
                        )
                    } else if (response.code.isNullOrBlank()) {
                        complete(
                            generation,
                            WechatAuthNativeResult(
                                WechatAuthNativeState.PROVIDER_ERROR,
                                reason = "MISSING_CREDENTIAL",
                            ),
                        )
                    } else {
                        complete(
                            generation,
                            WechatAuthNativeResult(
                                WechatAuthNativeState.CREDENTIAL_ACQUIRED,
                                credential = response.code,
                            ),
                        )
                    }
                }
                else -> complete(
                    generation,
                    WechatAuthNativeResult(
                        WechatAuthNativeState.PROVIDER_ERROR,
                        reason = "CALLBACK_ERROR",
                    ),
                )
            }
        }
        if (!installed) {
            cancelTimeout()
            synchronized(lock) {
                if (pending?.generation == generation) pending = null
            }
            completion(unavailable("REQUEST_IN_PROGRESS"))
            return
        }
        try {
            if (!client.sendAuthRequest(state)) {
                complete(
                    generation,
                    WechatAuthNativeResult(
                        WechatAuthNativeState.PROVIDER_ERROR,
                        reason = "REQUEST_REJECTED",
                    ),
                )
            }
        } catch (_: Throwable) {
            complete(
                generation,
                WechatAuthNativeResult(
                    WechatAuthNativeState.PROVIDER_ERROR,
                    reason = "REQUEST_FAILED",
                ),
            )
        }
    }

    override fun cancel(completion: (WechatAuthNativeResult) -> Unit) {
        val request = synchronized(lock) { pending?.also { pending = null } }
        if (request != null) {
            request.cancelTimeout()
            WechatAuthCallbackRegistry.clear(request.generation)
            request.completion(
                WechatAuthNativeResult(
                    WechatAuthNativeState.CANCELLED,
                    reason = "USER_CANCELLED",
                ),
            )
        }
        completion(WechatAuthNativeResult(WechatAuthNativeState.CANCELLED))
    }

    override fun revokePrivacy(completion: (WechatAuthNativeResult) -> Unit) {
        val request = synchronized(lock) {
            privacyGranted = false
            initialized = false
            sdk = null
            pending?.also { pending = null }
        }
        if (request != null) {
            request.cancelTimeout()
            WechatAuthCallbackRegistry.clear(request.generation)
            request.completion(
                WechatAuthNativeResult(
                    WechatAuthNativeState.CANCELLED,
                    reason = "PRIVACY_REVOKED",
                ),
            )
        }
        completion(unavailable("PRIVACY_REVOKED"))
    }

    private fun complete(generation: Long, result: WechatAuthNativeResult) {
        val request = synchronized(lock) {
            val current = pending
            if (current?.generation != generation) null else {
                pending = null
                current
            }
        } ?: return
        request.cancelTimeout()
        WechatAuthCallbackRegistry.clear(generation)
        request.completion(result)
    }

    private fun unavailable(reason: String) =
        WechatAuthNativeResult(WechatAuthNativeState.UNAVAILABLE, reason = reason)
}

private class WechatOpenSdkClientImpl(
    private val api: IWXAPI,
    private val appId: String,
) : WechatOpenSdkClient {
    override fun registerApp(): Boolean = api.registerApp(appId)

    override fun isWXAppInstalled(): Boolean = api.isWXAppInstalled

    override fun getWXAppSupportAPI(): Int = api.getWXAppSupportAPI()

    override fun sendAuthRequest(state: String): Boolean {
        val request = SendAuth.Req().apply {
            scope = "snsapi_userinfo"
            this.state = state
        }
        return api.sendReq(request)
    }
}
