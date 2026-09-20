package cn.jiyidashi.jiyidashi

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionSamplingNativeTest {
    @Test
    fun samplingProfileRejectsHighFrequencyOrInvalidThresholds() {
        assertNull(
            NativeSamplingProfile.validated(
                motionState = NativeMotionState.WALKING,
                minIntervalMs = 5_000L,
                minDistanceMeters = 20.0,
                maxAccuracyMeters = 80.0,
            ),
        )
        assertNull(
            NativeSamplingProfile.validated(
                motionState = NativeMotionState.WALKING,
                minIntervalMs = 60_000L,
                minDistanceMeters = 1.0,
                maxAccuracyMeters = 80.0,
            ),
        )
        val accepted = NativeSamplingProfile.validated(
            motionState = NativeMotionState.VEHICLE,
            minIntervalMs = 30_000L,
            minDistanceMeters = 100.0,
            maxAccuracyMeters = 100.0,
        )
        assertEquals(NativeMotionState.VEHICLE, accepted?.motionState)
        assertEquals(30_000L, accepted?.minIntervalMs)
    }

    @Test
    fun platformSignalMapperTreatsUnavailableValuesAsUnknown() {
        assertNull(NativeMotionSignalMapper.normalizedSpeed(false, 12f))
        assertNull(NativeMotionSignalMapper.normalizedSpeed(true, -1f))
        assertEquals(2.5f, NativeMotionSignalMapper.normalizedSpeed(true, 2.5f))

        assertNull(NativeMotionSignalMapper.normalizedAccuracy(false, 20f))
        assertNull(NativeMotionSignalMapper.normalizedAccuracy(true, -1f))
        assertEquals(18f, NativeMotionSignalMapper.normalizedAccuracy(true, 18f))
    }

    @Test
    fun cadenceGatePreventsCrossProviderBursts() {
        assertTrue(
            NativeLocationSampleAdmission.cadenceAllows(
                previousRecordedAtMillis = null,
                candidateRecordedAtMillis = 10_000L,
                minIntervalMs = 60_000L,
            ),
        )
        assertFalse(
            NativeLocationSampleAdmission.cadenceAllows(
                previousRecordedAtMillis = 10_000L,
                candidateRecordedAtMillis = 50_000L,
                minIntervalMs = 60_000L,
            ),
        )
        assertTrue(
            NativeLocationSampleAdmission.cadenceAllows(
                previousRecordedAtMillis = 10_000L,
                candidateRecordedAtMillis = 70_000L,
                minIntervalMs = 60_000L,
            ),
        )
    }

    @Test
    fun nativeRawQueueQuotaIsOwnerLocal() {
        val ownerA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        val ownerB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        val samples = List(1000) { index ->
            NativeQueuedLocationSample(
                ownerUserId = ownerA,
                clientUuid = "sample-$index",
                latitude = 0.0,
                longitude = 0.0,
                accuracyMeters = 20f,
                speedMetersPerSecond = 0f,
                recordedAtMillis = index.toLong(),
            )
        }
        // [人工注释][S2-004/005] A's full backlog may block only A, never B.
        assertFalse(NativeOwnerQueueQuota.hasCapacity(samples, ownerA, 1000))
        assertTrue(NativeOwnerQueueQuota.hasCapacity(samples, ownerB, 1000))
    }

    @Test
    fun qualityGateDropsOnlyKnownFixesWorseThanProfileCap() {
        val profile = NativeSamplingProfile.DEFAULT
        assertTrue(NativeLocationSampleAdmission.accepts(null, profile))
        assertTrue(NativeLocationSampleAdmission.accepts(80f, profile))
        assertFalse(NativeLocationSampleAdmission.accepts(180f, profile))
    }
}
