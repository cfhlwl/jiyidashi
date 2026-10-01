package cn.jiyidashi.jiyidashi

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeLocationPolicyTest {
    private val owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    @Test
    fun recordingHealthRuntimeAndBatteryProjectionAreDeterministic() {
        assertEquals(
            "eligible",
            NativeLocationPolicy.recordingBackgroundRuntimeState(backgroundRestricted = false),
        )
        assertEquals(
            "restricted",
            NativeLocationPolicy.recordingBackgroundRuntimeState(backgroundRestricted = true),
        )
        assertEquals(
            "not_applicable",
            NativeLocationPolicy.recordingBatteryOptimizationState(
                sdkInt = 22,
                ignoringBatteryOptimizations = false,
            ),
        )
        assertEquals(
            "optimized",
            NativeLocationPolicy.recordingBatteryOptimizationState(
                sdkInt = 35,
                ignoringBatteryOptimizations = false,
            ),
        )
        assertEquals(
            "exempt",
            NativeLocationPolicy.recordingBatteryOptimizationState(
                sdkInt = 35,
                ignoringBatteryOptimizations = true,
            ),
        )
    }

    @Test
    fun startRequiresBackgroundPermissionAndMatchingOwner() {
        assertTrue(
            NativeLocationPolicy.canStart(
                owner,
                owner,
                NativeLocationPermissionLevel.BACKGROUND,
                true,
            ),
        )
        assertFalse(
            NativeLocationPolicy.canStart(
                owner,
                owner,
                NativeLocationPermissionLevel.FOREGROUND,
                true,
            ),
        )
        assertFalse(
            NativeLocationPolicy.canStart(
                owner,
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                NativeLocationPermissionLevel.BACKGROUND,
                true,
            ),
        )
    }

    @Test
    fun backgroundPermissionPathIsProgressiveAndSdkAware() {
        assertEquals(
            BackgroundPermissionAction.NONE,
            NativeLocationPolicy.backgroundPermissionAction(
                explicitAutomaticEnable = false,
                permission = NativeLocationPermissionLevel.FOREGROUND,
                sdkInt = 30,
            ),
        )
        assertEquals(
            BackgroundPermissionAction.NONE,
            NativeLocationPolicy.backgroundPermissionAction(
                explicitAutomaticEnable = true,
                permission = NativeLocationPermissionLevel.NOT_DETERMINED,
                sdkInt = 30,
            ),
        )
        assertEquals(
            BackgroundPermissionAction.RUNTIME_REQUEST,
            NativeLocationPolicy.backgroundPermissionAction(
                explicitAutomaticEnable = true,
                permission = NativeLocationPermissionLevel.FOREGROUND,
                sdkInt = 29,
            ),
        )
        assertEquals(
            BackgroundPermissionAction.OPEN_SETTINGS,
            NativeLocationPolicy.backgroundPermissionAction(
                explicitAutomaticEnable = true,
                permission = NativeLocationPermissionLevel.FOREGROUND,
                sdkInt = 30,
            ),
        )
    }

    @Test
    fun differentAuthenticatedOwnerMustStopOldProducer() {
        assertTrue(
            NativeLocationPolicy.shouldStopCrossOwnerProducer(
                activeOwnerUserId = owner,
                currentOwnerUserId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            ),
        )
        assertFalse(
            NativeLocationPolicy.shouldStopCrossOwnerProducer(
                activeOwnerUserId = owner,
                currentOwnerUserId = owner,
            ),
        )
        assertFalse(
            NativeLocationPolicy.shouldStopCrossOwnerProducer(
                activeOwnerUserId = null,
                currentOwnerUserId = owner,
            ),
        )
    }

    @Test
    fun revokedPermissionForcesRunningProducerToStopped() {
        assertEquals(
            NativeLocationRuntimeState.STOPPED,
            NativeLocationPolicy.reconcileRuntime(
                ownerUserId = owner,
                enabledOwnerUserId = owner,
                permission = NativeLocationPermissionLevel.FOREGROUND,
                locationServicesEnabled = true,
                runtime = NativeLocationRuntimeState.RUNNING,
                nativeProducerActive = true,
            ),
        )
        assertEquals(
            NativeLocationRuntimeState.STOPPED,
            NativeLocationPolicy.reconcileRuntime(
                ownerUserId = owner,
                enabledOwnerUserId = owner,
                permission = NativeLocationPermissionLevel.BACKGROUND,
                locationServicesEnabled = false,
                runtime = NativeLocationRuntimeState.RUNNING,
                nativeProducerActive = true,
            ),
        )
    }

    @Test
    fun inactiveNativeProducerCannotRemainLogicallyRunning() {
        assertEquals(
            NativeLocationRuntimeState.STOPPED,
            NativeLocationPolicy.reconcileRuntime(
                ownerUserId = owner,
                enabledOwnerUserId = owner,
                permission = NativeLocationPermissionLevel.BACKGROUND,
                locationServicesEnabled = true,
                runtime = NativeLocationRuntimeState.RUNNING,
                nativeProducerActive = false,
            ),
        )
    }
    @Test
    fun processDeathRecoveryRequiresSameEnabledOwnerAndMissingProducer() {
        assertTrue(
            NativeLocationPolicy.shouldRecoverAfterProcessDeath(
                enabledOwnerUserId = owner,
                activeOwnerUserId = owner,
                runtime = NativeLocationRuntimeState.RUNNING,
                nativeProducerActive = false,
            ),
        )
        assertFalse(
            NativeLocationPolicy.shouldRecoverAfterProcessDeath(
                enabledOwnerUserId = owner,
                activeOwnerUserId = owner,
                runtime = NativeLocationRuntimeState.RUNNING,
                nativeProducerActive = true,
            ),
        )
        assertFalse(
            NativeLocationPolicy.shouldRecoverAfterProcessDeath(
                enabledOwnerUserId = owner,
                activeOwnerUserId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                runtime = NativeLocationRuntimeState.RUNNING,
                nativeProducerActive = false,
            ),
        )
        assertFalse(
            NativeLocationPolicy.shouldRecoverAfterProcessDeath(
                enabledOwnerUserId = null,
                activeOwnerUserId = owner,
                runtime = NativeLocationRuntimeState.RUNNING,
                nativeProducerActive = false,
            ),
        )
        assertFalse(
            NativeLocationPolicy.shouldRecoverAfterProcessDeath(
                enabledOwnerUserId = owner,
                activeOwnerUserId = owner,
                runtime = NativeLocationRuntimeState.PAUSED,
                nativeProducerActive = false,
            ),
        )
    }

    @Test
    fun queuedSampleV2MetadataIsStableAndPublishedToFlutter() {
        val sample = NativeQueuedLocationSample(
            ownerUserId = owner,
            clientUuid = "11111111-1111-4111-8111-111111111111",
            latitude = 3.139,
            longitude = 101.6869,
            accuracyMeters = 18f,
            speedMetersPerSecond = 1.5f,
            recordedAtMillis = 1_790_820_000_000L,
            queueSequence = 42L,
            enqueuedAtMillis = 1_790_820_001_000L,
            handoffAttemptCount = 3,
        )

        val platform = sample.toPlatformMap()
        assertEquals(42L, platform["queue_sequence"])
        assertEquals(1_790_820_001_000L, platform["enqueued_at_millis"])
        assertEquals(3, platform["handoff_attempt_count"])
        assertEquals("11111111-1111-4111-8111-111111111111", platform["client_uuid"])
    }

}
