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

        assertEquals(
            PhoneOneTapNativeState.UNAVAILABLE,
            adapter.initialize(privacyConsentGranted = false).state,
        )
        assertEquals(
            "PRIVACY_NOT_ACCEPTED",
            adapter.initialize(privacyConsentGranted = false).reason,
        )
        assertEquals(
            "PNVS_NOT_CONFIGURED",
            adapter.initialize(privacyConsentGranted = true).reason,
        )
        assertEquals(
            PhoneOneTapNativeState.UNAVAILABLE,
            adapter.checkAvailability().state,
        )
        assertEquals(
            PhoneOneTapNativeState.UNAVAILABLE,
            adapter.requestLoginToken(activityAvailable = true).state,
        )
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
    fun platformResultDoesNotRequireProviderTypes() {
        val result = PhoneOneTapNativeResult(
            PhoneOneTapNativeState.TOKEN_ACQUIRED,
            loginToken = "opaque-token",
        )

        assertEquals("TOKEN_ACQUIRED", result.toPlatformMap()["state"])
        assertEquals("opaque-token", result.toPlatformMap()["login_token"])
    }
}
