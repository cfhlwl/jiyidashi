package com.jiyidays

import android.app.Activity
import android.app.Application
import android.os.Handler
import android.os.Looper
import java.util.concurrent.atomic.AtomicBoolean

/** Provider-neutral state exposed by the JiYi bridge. */
enum class PhoneOneTapNativeState {
    AVAILABLE,
    UNAVAILABLE,
    CANCELLED,
    TIMEOUT,
    PROVIDER_ERROR,
    TOKEN_ACQUIRED,
}

data class PhoneOneTapNativeResult(
    val state: PhoneOneTapNativeState,
    val loginToken: String? = null,
    val reason: String? = null,
) {
    fun toPlatformMap(): Map<String, Any> = buildMap {
        put("state", state.name)
        if (loginToken != null) put("login_token", loginToken)
        if (reason != null) put("reason", reason)
    }
}

/**
 * A small lifecycle fence shared by the real adapter and the fail-closed seam.
 * A late callback may only complete the generation that created it.
 */
class PhoneOneTapRequestGate {
    private var nextGeneration = 0L
    private var activeGeneration: Long? = null

    @Synchronized
    fun begin(): Long? {
        if (activeGeneration != null) return null
        nextGeneration += 1
        activeGeneration = nextGeneration
        return activeGeneration
    }

    @Synchronized
    fun isCurrent(generation: Long): Boolean = activeGeneration == generation

    @Synchronized
    fun finish(generation: Long): Boolean {
        if (activeGeneration != generation) return false
        activeGeneration = null
        return true
    }

    @Synchronized
    fun invalidate() {
        activeGeneration = null
        nextGeneration += 1
    }

    @Synchronized
    fun hasActiveRequest(): Boolean = activeGeneration != null
}

/** Provider-neutral adapter boundary for the future official PNVS SDK adapter. */
typealias PhoneOneTapCompletion = (PhoneOneTapNativeResult) -> Unit

interface PhoneOneTapProviderAdapter {
    fun initialize(privacyConsentGranted: Boolean, completion: PhoneOneTapCompletion)
    fun checkAvailability(completion: PhoneOneTapCompletion)
    fun preLogin(completion: PhoneOneTapCompletion)
    fun requestLoginToken(activity: Activity, completion: PhoneOneTapCompletion)
    fun cancel(completion: PhoneOneTapCompletion)
    fun revokePrivacy(completion: PhoneOneTapCompletion)
}

/**
 * AUTH-02C deliberately ships no guessed Alibaba AAR/version/configuration.
 * Until the console-provided official SDK and final scheme are reviewed, every
 * live capability is unavailable.
 */
class FailClosedPhoneOneTapProviderAdapter : PhoneOneTapProviderAdapter {
    private var initialized = false

    override fun initialize(
        privacyConsentGranted: Boolean,
        completion: PhoneOneTapCompletion,
    ) {
        if (!privacyConsentGranted) {
            initialized = false
            completion(PhoneOneTapNativeResult(
                PhoneOneTapNativeState.UNAVAILABLE,
                reason = "PRIVACY_NOT_ACCEPTED",
            ))
            return
        }
        initialized = false
        completion(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.UNAVAILABLE,
            reason = "PNVS_NOT_CONFIGURED",
        ))
    }

    override fun checkAvailability(completion: PhoneOneTapCompletion) {
        if (!initialized) {
            completion(PhoneOneTapNativeResult(
                PhoneOneTapNativeState.UNAVAILABLE,
                reason = "NOT_INITIALIZED",
            ))
            return
        }
        completion(PhoneOneTapNativeResult(
            PhoneOneTapNativeState.UNAVAILABLE,
            reason = "PNVS_NOT_CONFIGURED",
        ))
    }

    override fun preLogin(completion: PhoneOneTapCompletion) = completion(unavailable())

    override fun requestLoginToken(
        activity: Activity,
        completion: PhoneOneTapCompletion,
    ) {
        completion(unavailable())
    }

    override fun cancel(completion: PhoneOneTapCompletion) =
        completion(PhoneOneTapNativeResult(PhoneOneTapNativeState.CANCELLED))

    override fun revokePrivacy(completion: PhoneOneTapCompletion) {
        initialized = false
        completion(unavailable("PRIVACY_REVOKED"))
    }

    private fun unavailable(reason: String = "PNVS_NOT_CONFIGURED") =
        PhoneOneTapNativeResult(PhoneOneTapNativeState.UNAVAILABLE, reason = reason)
}

/**
 * Application-level foreground fence. Activity pause is intentionally ignored:
 * the PNVS authorization page may create an Activity transition of its own.
 * The callback fires only after the process has no started Activities and the
 * short grace period has elapsed.
 */
class PhoneOneTapApplicationLifecycleFence(
    private val onRealBackgrounded: () -> Unit,
    private val handler: Handler? = null,
    private val scheduleBackgroundCheck: ((Long, () -> Unit) -> Unit)? = null,
    private val isChangingConfigurations: (Activity) -> Boolean = { it.isChangingConfigurations },
) : Application.ActivityLifecycleCallbacks {
    private var startedActivityCount = 0
    private var generation = 0L

    fun register(application: Application) {
        application.registerActivityLifecycleCallbacks(this)
    }

    fun unregister(application: Application) {
        application.unregisterActivityLifecycleCallbacks(this)
        generation += 1
    }

    override fun onActivityStarted(activity: Activity) {
        startedActivityCount += 1
        generation += 1
    }

    override fun onActivityStopped(activity: Activity) {
        startedActivityCount = (startedActivityCount - 1).coerceAtLeast(0)
        if (startedActivityCount != 0 || isChangingConfigurations(activity)) return
        val scheduledGeneration = ++generation
        val schedule = scheduleBackgroundCheck ?: { delay: Long, task: () -> Unit ->
            (handler ?: Handler(Looper.getMainLooper())).postDelayed(task, delay)
        }
        schedule(300L) {
            if (scheduledGeneration == generation && startedActivityCount == 0) {
                onRealBackgrounded()
            }
        }
    }

    override fun onActivityCreated(activity: Activity, state: android.os.Bundle?) = Unit
    override fun onActivityResumed(activity: Activity) = Unit
    override fun onActivityPaused(activity: Activity) = Unit
    override fun onActivitySaveInstanceState(activity: Activity, state: android.os.Bundle) = Unit
    override fun onActivityDestroyed(activity: Activity) = Unit
}

/** Guards a provider callback and makes duplicate callbacks harmless. */
class PhoneOneTapCallbackFence(
    private val gate: PhoneOneTapRequestGate,
    private val generation: Long,
    private val completion: PhoneOneTapCompletion,
) {
    private val completed = AtomicBoolean(false)

    fun complete(result: PhoneOneTapNativeResult): Boolean {
        if (!completed.compareAndSet(false, true) || !gate.finish(generation)) {
            return false
        }
        completion(result)
        return true
    }
}
