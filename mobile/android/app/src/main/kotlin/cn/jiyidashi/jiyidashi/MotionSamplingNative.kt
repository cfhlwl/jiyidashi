package cn.jiyidashi.jiyidashi

enum class NativeMotionState(val wireValue: String) {
    UNKNOWN("unknown"),
    STATIONARY("stationary"),
    WALKING("walking"),
    VEHICLE("vehicle");

    companion object {
        fun fromWire(value: String?): NativeMotionState =
            entries.firstOrNull { it.wireValue == value } ?: UNKNOWN
    }
}

data class NativeSamplingProfile(
    val motionState: NativeMotionState,
    val minIntervalMs: Long,
    val minDistanceMeters: Float,
    val maxAccuracyMeters: Float,
) {
    companion object {
        val DEFAULT = NativeSamplingProfile(
            motionState = NativeMotionState.UNKNOWN,
            minIntervalMs = 120_000L,
            minDistanceMeters = 75f,
            maxAccuracyMeters = 120f,
        )

        fun validated(
            motionState: NativeMotionState,
            minIntervalMs: Long,
            minDistanceMeters: Double,
            maxAccuracyMeters: Double,
        ): NativeSamplingProfile? {
            if (minIntervalMs < 15_000L ||
                minDistanceMeters < 5.0 ||
                !minDistanceMeters.isFinite() ||
                maxAccuracyMeters < 10.0 ||
                !maxAccuracyMeters.isFinite()
            ) {
                return null
            }
            return NativeSamplingProfile(
                motionState = motionState,
                minIntervalMs = minIntervalMs,
                minDistanceMeters = minDistanceMeters.toFloat(),
                maxAccuracyMeters = maxAccuracyMeters.toFloat(),
            )
        }
    }
}

data class NativeQueuedLocationSample(
    val ownerUserId: String,
    val clientUuid: String,
    val latitude: Double,
    val longitude: Double,
    val accuracyMeters: Float?,
    val speedMetersPerSecond: Float?,
    val recordedAtMillis: Long,
) {
    fun toPlatformMap(): Map<String, Any?> =
        mapOf(
            "client_uuid" to clientUuid,
            "latitude" to latitude,
            "longitude" to longitude,
            "accuracy" to accuracyMeters,
            "speed" to speedMetersPerSecond,
            "recorded_at_millis" to recordedAtMillis,
        )
}

data class NativeMotionObservation(
    val ownerUserId: String,
    val accuracyMeters: Float?,
    val speedMetersPerSecond: Float?,
    val recordedAtMillis: Long,
)

object NativeOwnerQueueQuota {
    fun hasCapacity(
        samples: List<NativeQueuedLocationSample>,
        ownerUserId: String,
        maxPerOwner: Int,
    ): Boolean {
        if (maxPerOwner <= 0) return false
        // [人工注释][S2-004/005] raw GPS backpressure is owner-local: one signed-out
        // account's backlog must never exhaust a different signed-in owner's admission quota.
        return samples.count { it.ownerUserId == ownerUserId } < maxPerOwner
    }
}

/// Platform mapping is deliberately pure so JVM tests can lock Android's "unavailable"
/// semantics without constructing android.location.Location or requiring an emulator.
object NativeMotionSignalMapper {
    fun normalizedSpeed(hasSpeed: Boolean, speedMetersPerSecond: Float): Float? {
        if (!hasSpeed || !speedMetersPerSecond.isFinite() || speedMetersPerSecond < 0f) {
            return null
        }
        return speedMetersPerSecond
    }

    fun normalizedAccuracy(hasAccuracy: Boolean, accuracyMeters: Float): Float? {
        if (!hasAccuracy || !accuracyMeters.isFinite() || accuracyMeters < 0f) {
            return null
        }
        return accuracyMeters
    }
}

object NativeLocationSampleAdmission {
    fun accepts(
        accuracyMeters: Float?,
        profile: NativeSamplingProfile,
    ): Boolean {
        return accuracyMeters == null || accuracyMeters <= profile.maxAccuracyMeters
    }

    fun cadenceAllows(
        previousRecordedAtMillis: Long?,
        candidateRecordedAtMillis: Long,
        minIntervalMs: Long,
    ): Boolean {
        if (previousRecordedAtMillis == null) return true
        return candidateRecordedAtMillis - previousRecordedAtMillis >= minIntervalMs
    }
}
