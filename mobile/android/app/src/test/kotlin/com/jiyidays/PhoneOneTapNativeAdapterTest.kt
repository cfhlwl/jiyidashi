package com.jiyidays

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
        adapter.requestLoginToken(activityAvailable = true) { result = it }
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
}
