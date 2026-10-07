package com.jiyidays

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PassiveRecoveryArbiterTest {
    @Test
    fun attachedForegroundEngineBlocksHeadlessRefreshClaim() {
        val arbiter = PassiveRecoveryArbiter<String>()

        arbiter.attachEngine()

        assertFalse(arbiter.tryBeginHeadless())
        assertEquals(1, arbiter.snapshot().attachedEngineCount)
        assertFalse(arbiter.snapshot().headlessActive)
    }

    @Test
    fun foregroundAttachDuringHeadlessClaimWaitsUntilRelease() {
        val arbiter = PassiveRecoveryArbiter<String>()

        assertTrue(arbiter.tryBeginHeadless())
        arbiter.attachEngine()

        assertFalse(arbiter.awaitIdle("foreground-restore"))
        assertEquals(1, arbiter.snapshot().waiterCount)

        val released = arbiter.finishHeadless()

        assertEquals(listOf("foreground-restore"), released)
        assertFalse(arbiter.snapshot().headlessActive)
        // The attached foreground engine now owns refresh responsibility, so another
        // headless worker must still be rejected after the old worker releases its lease.
        assertFalse(arbiter.tryBeginHeadless())

        arbiter.detachEngine()
        assertTrue(arbiter.tryBeginHeadless())
    }

    @Test
    fun concurrentHeadlessClaimsAreSingleWinnerAndWaitersReleaseOnce() {
        val arbiter = PassiveRecoveryArbiter<String>()

        assertTrue(arbiter.tryBeginHeadless())
        assertFalse(arbiter.tryBeginHeadless())
        assertFalse(arbiter.awaitIdle("a"))
        assertFalse(arbiter.awaitIdle("b"))

        assertEquals(listOf("a", "b"), arbiter.finishHeadless())
        assertTrue(arbiter.awaitIdle("late"))
        assertTrue(arbiter.finishHeadless().isEmpty())
    }

    @Test
    fun duplicateDetachCannotUnderflowEngineCount() {
        val arbiter = PassiveRecoveryArbiter<String>()

        arbiter.attachEngine()
        arbiter.detachEngine()
        arbiter.detachEngine()

        assertEquals(0, arbiter.snapshot().attachedEngineCount)
        assertTrue(arbiter.tryBeginHeadless())
    }
}
