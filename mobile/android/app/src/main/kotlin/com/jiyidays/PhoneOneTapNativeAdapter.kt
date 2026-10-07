package com.jiyidays

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
interface PhoneOneTapProviderAdapter {
    fun initialize(privacyConsentGranted: Boolean): PhoneOneTapNativeResult
    fun checkAvailability(): PhoneOneTapNativeResult
    fun preLogin(): PhoneOneTapNativeResult
    fun requestLoginToken(activityAvailable: Boolean): PhoneOneTapNativeResult
    fun cancel(): PhoneOneTapNativeResult
}

/**
 * AUTH-02C deliberately ships no guessed Alibaba AAR/version/configuration.
 * Until the console-provided official SDK and final scheme are reviewed, every
 * live capability is unavailable.
 */
class FailClosedPhoneOneTapProviderAdapter : PhoneOneTapProviderAdapter {
    private var initialized = false

    override fun initialize(privacyConsentGranted: Boolean): PhoneOneTapNativeResult {
        if (!privacyConsentGranted) {
            initialized = false
            return PhoneOneTapNativeResult(
                PhoneOneTapNativeState.UNAVAILABLE,
                reason = "PRIVACY_NOT_ACCEPTED",
            )
        }
        initialized = false
        return PhoneOneTapNativeResult(
            PhoneOneTapNativeState.UNAVAILABLE,
            reason = "PNVS_NOT_CONFIGURED",
        )
    }

    override fun checkAvailability(): PhoneOneTapNativeResult {
        if (!initialized) {
            return PhoneOneTapNativeResult(
                PhoneOneTapNativeState.UNAVAILABLE,
                reason = "NOT_INITIALIZED",
            )
        }
        return PhoneOneTapNativeResult(
            PhoneOneTapNativeState.UNAVAILABLE,
            reason = "PNVS_NOT_CONFIGURED",
        )
    }

    override fun preLogin(): PhoneOneTapNativeResult = unavailable()

    override fun requestLoginToken(activityAvailable: Boolean): PhoneOneTapNativeResult {
        if (!activityAvailable) return unavailable("ACTIVITY_UNAVAILABLE")
        return unavailable()
    }

    override fun cancel(): PhoneOneTapNativeResult =
        PhoneOneTapNativeResult(PhoneOneTapNativeState.CANCELLED)

    private fun unavailable(reason: String = "PNVS_NOT_CONFIGURED") =
        PhoneOneTapNativeResult(PhoneOneTapNativeState.UNAVAILABLE, reason = reason)
}
