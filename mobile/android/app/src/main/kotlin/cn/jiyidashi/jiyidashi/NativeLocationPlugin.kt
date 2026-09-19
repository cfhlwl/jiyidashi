package cn.jiyidashi.jiyidashi

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.PluginRegistry
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

class NativeLocationPlugin :
    FlutterPlugin,
    MethodChannel.MethodCallHandler,
    ActivityAware,
    PluginRegistry.RequestPermissionsResultListener {
    private lateinit var applicationContext: Context
    private lateinit var channel: MethodChannel
    private lateinit var store: NativeLocationStore
    private var activity: Activity? = null
    private var activityBinding: ActivityPluginBinding? = null
    private var pendingRequest: PendingPermissionRequest? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        applicationContext = binding.applicationContext
        store = NativeLocationStore(applicationContext)
        channel = MethodChannel(binding.binaryMessenger, CHANNEL_NAME)
        channel.setMethodCallHandler(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel.setMethodCallHandler(null)
        pendingRequest?.result?.error("bridge_detached", "Location bridge detached", null)
        pendingRequest = null
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
        activityBinding = binding
        binding.addRequestPermissionsResultListener(this)
    }

    override fun onDetachedFromActivityForConfigChanges() {
        detachActivity()
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        onAttachedToActivity(binding)
    }

    override fun onDetachedFromActivity() {
        detachActivity()
    }

    private fun detachActivity() {
        activityBinding?.removeRequestPermissionsResultListener(this)
        activityBinding = null
        activity = null
        pendingRequest?.result?.error(
            "activity_detached",
            "Location permission request was interrupted",
            null,
        )
        pendingRequest = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        val ownerUserId = ownerFrom(call)
        if (ownerUserId == null) {
            result.error("invalid_owner", "Authenticated user id is required", null)
            return
        }

        when (call.method) {
            "status" -> result.success(status(ownerUserId))
            "requestForegroundPermission" ->
                requestForegroundPermission(ownerUserId, result)
            "enableAutomaticLocation" ->
                enableAutomaticLocation(ownerUserId, result)
            "openBackgroundLocationSettings" ->
                openBackgroundLocationSettings(ownerUserId, result)
            "disableAutomaticLocation" ->
                result.success(disableAutomaticLocation(ownerUserId))
            "start" -> result.success(start(ownerUserId))
            "pause" -> result.success(pause(ownerUserId))
            "stop" -> result.success(stop(ownerUserId))
            else -> result.notImplemented()
        }
    }

    private fun ownerFrom(call: MethodCall): String? {
        val owner = call.argument<String>("owner_user_id")?.trim().orEmpty()
        return owner.takeIf { it.isNotEmpty() }
    }

    private fun requestForegroundPermission(
        ownerUserId: String,
        result: MethodChannel.Result,
    ) {
        if (AndroidLocationPermissions.foregroundGranted(applicationContext)) {
            result.success(status(ownerUserId))
            return
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            result.success(status(ownerUserId))
            return
        }
        val currentActivity = activity
        if (currentActivity == null) {
            result.error("no_activity", "Location permission requires a foreground activity", null)
            return
        }
        if (pendingRequest != null) {
            result.error("permission_busy", "Another location permission request is active", null)
            return
        }

        store.foregroundPermissionRequested = true
        pendingRequest = PendingPermissionRequest(
            kind = PermissionRequestKind.FOREGROUND,
            ownerUserId = ownerUserId,
            result = result,
        )
        currentActivity.requestPermissions(
            arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION,
            ),
            REQUEST_FOREGROUND_LOCATION,
        )
    }

    private fun enableAutomaticLocation(
        ownerUserId: String,
        result: MethodChannel.Result,
    ) {
        val permission = AndroidLocationPermissions.level(applicationContext, store)
        if (permission == NativeLocationPermissionLevel.BACKGROUND) {
            switchAutomaticOwner(ownerUserId)
            result.success(status(ownerUserId))
            return
        }
        if (permission != NativeLocationPermissionLevel.FOREGROUND) {
            result.success(
                status(
                    ownerUserId,
                    forcedReason = if (permission == NativeLocationPermissionLevel.DENIED) {
                        "permission_denied"
                    } else {
                        "foreground_permission_required"
                    },
                ),
            )
            return
        }

        when (
            NativeLocationPolicy.backgroundPermissionAction(
                explicitAutomaticEnable = true,
                permission = permission,
                sdkInt = Build.VERSION.SDK_INT,
            )
        ) {
            BackgroundPermissionAction.NONE -> {
                // Pre-Android 10 foreground grant already covers background access.
                switchAutomaticOwner(ownerUserId)
                result.success(status(ownerUserId))
            }
            BackgroundPermissionAction.OPEN_SETTINGS -> {
                // Android 11+ no longer offers "Allow all the time" in the runtime dialog.
                // Persist only the user's explicit enable intent; a separate explicit UI
                // action opens Settings, and app-resume status() finalizes enablement only
                // after the OS reports a real background grant.
                store.backgroundPermissionRequested = true
                store.pendingEnableOwnerUserId = ownerUserId
                result.success(
                    status(
                        ownerUserId,
                        forcedReason = "background_settings_required",
                    ),
                )
            }
            BackgroundPermissionAction.RUNTIME_REQUEST -> {
                val currentActivity = activity
                if (currentActivity == null) {
                    result.error(
                        "no_activity",
                        "Background permission requires a foreground activity",
                        null,
                    )
                    return
                }
                if (pendingRequest != null) {
                    result.error(
                        "permission_busy",
                        "Another location permission request is active",
                        null,
                    )
                    return
                }

                store.backgroundPermissionRequested = true
                pendingRequest = PendingPermissionRequest(
                    kind = PermissionRequestKind.BACKGROUND,
                    ownerUserId = ownerUserId,
                    result = result,
                )
                currentActivity.requestPermissions(
                    arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION),
                    REQUEST_BACKGROUND_LOCATION,
                )
            }
        }
    }

    private fun openBackgroundLocationSettings(
        ownerUserId: String,
        result: MethodChannel.Result,
    ) {
        val permission = AndroidLocationPermissions.level(applicationContext, store)
        if (permission == NativeLocationPermissionLevel.BACKGROUND) {
            if (store.pendingEnableOwnerUserId == ownerUserId) {
                switchAutomaticOwner(ownerUserId)
            }
            result.success(status(ownerUserId))
            return
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R ||
            store.pendingEnableOwnerUserId != ownerUserId
        ) {
            result.success(
                status(ownerUserId, forcedReason = "background_permission_required"),
            )
            return
        }

        val currentActivity = activity
        if (currentActivity == null) {
            result.error(
                "no_activity",
                "Opening location settings requires a foreground activity",
                null,
            )
            return
        }

        val intent = Intent(
            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.parse("package:${applicationContext.packageName}"),
        )
        currentActivity.startActivity(intent)
        result.success(
            status(ownerUserId, forcedReason = "background_settings_required"),
        )
    }

    private fun switchAutomaticOwner(ownerUserId: String) {
        // Automatic enable is account-scoped. Switching accounts must stop any old producer
        // before the new owner preference becomes authoritative.
        if (store.enabledOwnerUserId != ownerUserId) {
            applicationContext.stopService(
                Intent(applicationContext, NativeLocationTrackingService::class.java),
            )
            store.runtime = NativeLocationRuntimeState.STOPPED
            store.activeOwnerUserId = null
            // Diagnostics are owner-local UX state. Clearing on owner switch prevents the
            // next account from seeing the previous account's last-fix time/accuracy.
            store.clearDiagnostics()
        }
        store.pendingEnableOwnerUserId = null
        store.enabledOwnerUserId = ownerUserId
    }

    private fun disableAutomaticLocation(ownerUserId: String): Map<String, Any?> {
        if (store.enabledOwnerUserId == ownerUserId || store.activeOwnerUserId == ownerUserId) {
            store.clearAutomaticOwner(ownerUserId)
            store.clearDiagnostics()
            store.runtime = NativeLocationRuntimeState.STOPPED
            applicationContext.stopService(
                Intent(applicationContext, NativeLocationTrackingService::class.java),
            )
        }
        return status(ownerUserId)
    }

    private fun start(ownerUserId: String): Map<String, Any?> {
        val permission = AndroidLocationPermissions.level(applicationContext, store)
        val servicesEnabled = AndroidLocationPermissions.locationServicesEnabled(applicationContext)
        if (
            !NativeLocationPolicy.canStart(
                ownerUserId = ownerUserId,
                enabledOwnerUserId = store.enabledOwnerUserId,
                permission = permission,
                locationServicesEnabled = servicesEnabled,
            )
        ) {
            if (store.activeOwnerUserId == ownerUserId) {
                applicationContext.stopService(
                    Intent(applicationContext, NativeLocationTrackingService::class.java),
                )
            }
            store.runtime = NativeLocationRuntimeState.STOPPED
            store.activeOwnerUserId = null
            return status(ownerUserId, forcedReason = startFailureReason(permission, servicesEnabled))
        }

        val intent = Intent(applicationContext, NativeLocationTrackingService::class.java)
            .putExtra(NativeLocationTrackingService.EXTRA_OWNER_USER_ID, ownerUserId)
        store.runtime = NativeLocationRuntimeState.RUNNING
        store.activeOwnerUserId = ownerUserId
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                applicationContext.startForegroundService(intent)
            } else {
                applicationContext.startService(intent)
            }
        } catch (_: RuntimeException) {
            store.runtime = NativeLocationRuntimeState.STOPPED
            store.activeOwnerUserId = null
            return status(ownerUserId, forcedReason = "native_start_failed")
        }
        // startForegroundService() schedules service creation asynchronously. This one return
        // may trust the permission/owner gate that was just checked; every later status()
        // requires the service's real isActive flag and will fail closed if startup failed.
        return status(ownerUserId, assumeProducerActive = true)
    }

    private fun pause(ownerUserId: String): Map<String, Any?> {
        if (store.activeOwnerUserId == ownerUserId || store.enabledOwnerUserId == ownerUserId) {
            store.runtime = NativeLocationRuntimeState.PAUSED
            store.activeOwnerUserId = null
            applicationContext.stopService(
                Intent(applicationContext, NativeLocationTrackingService::class.java),
            )
        }
        return status(ownerUserId)
    }

    private fun stop(ownerUserId: String): Map<String, Any?> {
        if (store.activeOwnerUserId == ownerUserId || store.enabledOwnerUserId == ownerUserId) {
            store.runtime = NativeLocationRuntimeState.STOPPED
            store.activeOwnerUserId = null
            applicationContext.stopService(
                Intent(applicationContext, NativeLocationTrackingService::class.java),
            )
        }
        return status(ownerUserId)
    }

    private fun status(
        ownerUserId: String,
        forcedReason: String? = null,
        assumeProducerActive: Boolean = false,
    ): Map<String, Any?> {
        val storedActiveOwner = store.activeOwnerUserId
        if (
            NativeLocationPolicy.shouldStopCrossOwnerProducer(
                activeOwnerUserId = storedActiveOwner,
                currentOwnerUserId = ownerUserId,
            )
        ) {
            // FGS may outlive the Flutter engine. A newly authenticated account must
            // reconcile and stop any old account's producer even if normal Logout never ran.
            applicationContext.stopService(
                Intent(applicationContext, NativeLocationTrackingService::class.java),
            )
            store.activeOwnerUserId = null
            store.runtime = NativeLocationRuntimeState.STOPPED
        }

        val permission = AndroidLocationPermissions.level(applicationContext, store)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            store.pendingEnableOwnerUserId == ownerUserId &&
            permission == NativeLocationPermissionLevel.BACKGROUND
        ) {
            // Returning from Settings is status-only: it observes the OS grant and finalizes
            // the enable intent that the user already made. It does not start the producer.
            switchAutomaticOwner(ownerUserId)
        }
        val servicesEnabled = AndroidLocationPermissions.locationServicesEnabled(applicationContext)
        val ownerMatches = store.enabledOwnerUserId == ownerUserId
        val activeOwnerMatches = store.activeOwnerUserId == ownerUserId
        val producerActive =
            activeOwnerMatches &&
                (NativeLocationTrackingService.isActive || assumeProducerActive)
        val reconciled = NativeLocationPolicy.reconcileRuntime(
            ownerUserId = ownerUserId,
            enabledOwnerUserId = store.enabledOwnerUserId,
            permission = permission,
            locationServicesEnabled = servicesEnabled,
            runtime = if (ownerMatches) store.runtime else NativeLocationRuntimeState.STOPPED,
            nativeProducerActive = producerActive,
        )

        if (activeOwnerMatches && reconciled != NativeLocationRuntimeState.RUNNING) {
            applicationContext.stopService(
                Intent(applicationContext, NativeLocationTrackingService::class.java),
            )
            store.activeOwnerUserId = null
        }
        if (ownerMatches && store.runtime == NativeLocationRuntimeState.RUNNING &&
            reconciled != NativeLocationRuntimeState.RUNNING
        ) {
            store.runtime = reconciled
        }

        val reason = forcedReason ?: when {
            !servicesEnabled -> "location_services_disabled"
            permission == NativeLocationPermissionLevel.DENIED -> "permission_denied"
            permission == NativeLocationPermissionLevel.NOT_DETERMINED -> "foreground_permission_required"
            permission == NativeLocationPermissionLevel.FOREGROUND &&
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
                store.pendingEnableOwnerUserId == ownerUserId ->
                "background_settings_required"
            permission == NativeLocationPermissionLevel.FOREGROUND && ownerMatches ->
                "background_permission_required"
            !ownerMatches -> "automatic_location_disabled"
            reconciled == NativeLocationRuntimeState.PAUSED -> "paused"
            else -> null
        }

        return mapOf(
            "supported" to true,
            "platform" to "android",
            "permission" to permissionValue(permission),
            "runtime" to runtimeValue(reconciled),
            "automatic_enabled" to ownerMatches,
            "location_services_enabled" to servicesEnabled,
            "reason" to reason,
            "last_fix_at" to if (ownerMatches) {
                store.lastFixAtMillis?.let { isoTimestamp(it) }
            } else {
                null
            },
            "last_accuracy_meters" to if (ownerMatches) store.lastAccuracyMeters else null,
        )
    }

    private fun isoTimestamp(epochMillis: Long): String {
        val formatter = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        formatter.timeZone = TimeZone.getTimeZone("UTC")
        return formatter.format(Date(epochMillis))
    }

    private fun startFailureReason(
        permission: NativeLocationPermissionLevel,
        servicesEnabled: Boolean,
    ): String {
        if (!servicesEnabled) return "location_services_disabled"
        if (store.enabledOwnerUserId == null) return "automatic_location_disabled"
        return when (permission) {
            NativeLocationPermissionLevel.BACKGROUND -> "owner_mismatch"
            NativeLocationPermissionLevel.FOREGROUND -> "background_permission_required"
            NativeLocationPermissionLevel.NOT_DETERMINED -> "foreground_permission_required"
            NativeLocationPermissionLevel.DENIED -> "permission_denied"
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ): Boolean {
        val pending = pendingRequest ?: return false
        val expected = when (pending.kind) {
            PermissionRequestKind.FOREGROUND -> REQUEST_FOREGROUND_LOCATION
            PermissionRequestKind.BACKGROUND -> REQUEST_BACKGROUND_LOCATION
        }
        if (requestCode != expected) return false

        pendingRequest = null
        if (
            pending.kind == PermissionRequestKind.BACKGROUND &&
            AndroidLocationPermissions.backgroundGranted(applicationContext)
        ) {
            switchAutomaticOwner(pending.ownerUserId)
        }
        pending.result.success(status(pending.ownerUserId))
        return true
    }

    private fun permissionValue(value: NativeLocationPermissionLevel): String {
        return when (value) {
            NativeLocationPermissionLevel.NOT_DETERMINED -> "not_determined"
            NativeLocationPermissionLevel.FOREGROUND -> "foreground"
            NativeLocationPermissionLevel.BACKGROUND -> "background"
            NativeLocationPermissionLevel.DENIED -> "denied"
        }
    }

    private fun runtimeValue(value: NativeLocationRuntimeState): String {
        return when (value) {
            NativeLocationRuntimeState.STOPPED -> "stopped"
            NativeLocationRuntimeState.PAUSED -> "paused"
            NativeLocationRuntimeState.RUNNING -> "running"
        }
    }

    private data class PendingPermissionRequest(
        val kind: PermissionRequestKind,
        val ownerUserId: String,
        val result: MethodChannel.Result,
    )

    private enum class PermissionRequestKind {
        FOREGROUND,
        BACKGROUND,
    }

    companion object {
        private const val CHANNEL_NAME = "cn.jiyidashi/native_location"
        private const val REQUEST_FOREGROUND_LOCATION = 2401
        private const val REQUEST_BACKGROUND_LOCATION = 2402
    }
}
