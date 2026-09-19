package cn.jiyidashi.jiyidashi

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeLocationPolicyTest {
    private val owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

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
}
