package cn.jiyidashi.jiyidashi

enum class NativeLocationPermissionLevel {
    NOT_DETERMINED,
    FOREGROUND,
    BACKGROUND,
    DENIED,
}

enum class NativeLocationRuntimeState {
    STOPPED,
    PAUSED,
    RUNNING,
}

enum class BackgroundPermissionAction {
    NONE,
    RUNTIME_REQUEST,
    OPEN_SETTINGS,
}

/**
 * Pure policy shared by the Android bridge and JVM tests.
 *
 * Permission ownership is intentionally separate from runtime state: an old account's
 * grant/enabled preference must never authorize a new account on the same device.
 */
object NativeLocationPolicy {
    fun recordingBackgroundRuntimeState(backgroundRestricted: Boolean?): String {
        return when (backgroundRestricted) {
            true -> "restricted"
            false -> "eligible"
            null -> "unknown"
        }
    }

    fun recordingBatteryOptimizationState(
        sdkInt: Int,
        ignoringBatteryOptimizations: Boolean?,
    ): String {
        if (sdkInt < 23) return "not_applicable"
        return when (ignoringBatteryOptimizations) {
            true -> "exempt"
            false -> "optimized"
            null -> "unknown"
        }
    }

    fun canStart(
        ownerUserId: String,
        enabledOwnerUserId: String?,
        permission: NativeLocationPermissionLevel,
        locationServicesEnabled: Boolean,
    ): Boolean {
        return ownerUserId.isNotBlank() &&
            ownerUserId == enabledOwnerUserId &&
            permission == NativeLocationPermissionLevel.BACKGROUND &&
            locationServicesEnabled
    }

    fun backgroundPermissionAction(
        explicitAutomaticEnable: Boolean,
        permission: NativeLocationPermissionLevel,
        sdkInt: Int,
    ): BackgroundPermissionAction {
        if (!explicitAutomaticEnable ||
            permission != NativeLocationPermissionLevel.FOREGROUND
        ) {
            return BackgroundPermissionAction.NONE
        }
        return when {
            sdkInt >= 30 -> BackgroundPermissionAction.OPEN_SETTINGS
            sdkInt >= 29 -> BackgroundPermissionAction.RUNTIME_REQUEST
            else -> BackgroundPermissionAction.NONE
        }
    }

    fun shouldStopCrossOwnerProducer(
        activeOwnerUserId: String?,
        currentOwnerUserId: String,
    ): Boolean {
        return activeOwnerUserId != null &&
            activeOwnerUserId != currentOwnerUserId
    }

    fun shouldRecoverAfterProcessDeath(
        enabledOwnerUserId: String?,
        activeOwnerUserId: String?,
        runtime: NativeLocationRuntimeState,
        nativeProducerActive: Boolean,
    ): Boolean {
        val enabled = enabledOwnerUserId?.trim().orEmpty()
        return enabled.isNotEmpty() &&
            activeOwnerUserId == enabled &&
            runtime == NativeLocationRuntimeState.RUNNING &&
            !nativeProducerActive
    }

    fun reconcileRuntime(
        ownerUserId: String,
        enabledOwnerUserId: String?,
        permission: NativeLocationPermissionLevel,
        locationServicesEnabled: Boolean,
        runtime: NativeLocationRuntimeState,
        nativeProducerActive: Boolean,
    ): NativeLocationRuntimeState {
        if (runtime != NativeLocationRuntimeState.RUNNING) {
            return runtime
        }
        if (!nativeProducerActive) {
            return NativeLocationRuntimeState.STOPPED
        }
        return if (
            canStart(
                ownerUserId = ownerUserId,
                enabledOwnerUserId = enabledOwnerUserId,
                permission = permission,
                locationServicesEnabled = locationServicesEnabled,
            )
        ) {
            NativeLocationRuntimeState.RUNNING
        } else {
            NativeLocationRuntimeState.STOPPED
        }
    }
}
