package cn.jiyidashi.jiyidashi

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class NotificationProviderSelectorTest {
    @Test
    fun huaweiProviderWinsWhenBothStacksAreAvailable() {
        assertEquals(
            "HMS",
            NotificationProviderSelector.select(
                hmsConfigured = true,
                hmsAvailable = true,
                fcmConfigured = true,
                gmsAvailable = true,
            ),
        )
    }

    @Test
    fun fcmIsUsedForGmsDeviceWhenHuaweiIsUnavailable() {
        assertEquals(
            "FCM",
            NotificationProviderSelector.select(
                hmsConfigured = true,
                hmsAvailable = false,
                fcmConfigured = true,
                gmsAvailable = true,
            ),
        )
    }

    @Test
    fun mainlandNonGmsWithoutReviewedHuaweiConfigFailsClosed() {
        assertNull(
            NotificationProviderSelector.select(
                hmsConfigured = false,
                hmsAvailable = true,
                fcmConfigured = true,
                gmsAvailable = false,
            ),
        )
    }
}
