package cn.jiyidashi.jiyidashi

import android.content.Context

internal class NativeLocationStore(context: Context) {
    private val prefs =
        context.getSharedPreferences("jiyidashi_native_location", Context.MODE_PRIVATE)

    var enabledOwnerUserId: String?
        get() = prefs.getString(KEY_ENABLED_OWNER, null)
        set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_ENABLED_OWNER) else putString(KEY_ENABLED_OWNER, value)
            }.apply()
        }

    var activeOwnerUserId: String?
        get() = prefs.getString(KEY_ACTIVE_OWNER, null)
        set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_ACTIVE_OWNER) else putString(KEY_ACTIVE_OWNER, value)
            }.apply()
        }

    var pendingEnableOwnerUserId: String?
        get() = prefs.getString(KEY_PENDING_ENABLE_OWNER, null)
        set(value) {
            prefs.edit().apply {
                if (value == null) {
                    remove(KEY_PENDING_ENABLE_OWNER)
                } else {
                    putString(KEY_PENDING_ENABLE_OWNER, value)
                }
            }.apply()
        }

    var runtime: NativeLocationRuntimeState
        get() = when (prefs.getString(KEY_RUNTIME, null)) {
            "running" -> NativeLocationRuntimeState.RUNNING
            "paused" -> NativeLocationRuntimeState.PAUSED
            else -> NativeLocationRuntimeState.STOPPED
        }
        set(value) {
            val raw = when (value) {
                NativeLocationRuntimeState.RUNNING -> "running"
                NativeLocationRuntimeState.PAUSED -> "paused"
                NativeLocationRuntimeState.STOPPED -> "stopped"
            }
            prefs.edit().putString(KEY_RUNTIME, raw).apply()
        }

    var foregroundPermissionRequested: Boolean
        get() = prefs.getBoolean(KEY_FOREGROUND_ASKED, false)
        set(value) {
            prefs.edit().putBoolean(KEY_FOREGROUND_ASKED, value).apply()
        }

    var backgroundPermissionRequested: Boolean
        get() = prefs.getBoolean(KEY_BACKGROUND_ASKED, false)
        set(value) {
            prefs.edit().putBoolean(KEY_BACKGROUND_ASKED, value).apply()
        }

    var lastFixAtMillis: Long?
        get() = if (prefs.contains(KEY_LAST_FIX_AT)) {
            prefs.getLong(KEY_LAST_FIX_AT, 0L)
        } else {
            null
        }
        set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_LAST_FIX_AT) else putLong(KEY_LAST_FIX_AT, value)
            }.apply()
        }

    var lastAccuracyMeters: Float?
        get() = if (prefs.contains(KEY_LAST_ACCURACY)) {
            prefs.getFloat(KEY_LAST_ACCURACY, 0f)
        } else {
            null
        }
        set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_LAST_ACCURACY) else putFloat(KEY_LAST_ACCURACY, value)
            }.apply()
        }

    fun clearAutomaticOwner(ownerUserId: String) {
        if (enabledOwnerUserId == ownerUserId) {
            enabledOwnerUserId = null
        }
        if (activeOwnerUserId == ownerUserId) {
            activeOwnerUserId = null
        }
        if (pendingEnableOwnerUserId == ownerUserId) {
            pendingEnableOwnerUserId = null
        }
    }

    fun clearDiagnostics() {
        lastFixAtMillis = null
        lastAccuracyMeters = null
    }

    companion object {
        private const val KEY_ENABLED_OWNER = "enabled_owner_user_id"
        private const val KEY_ACTIVE_OWNER = "active_owner_user_id"
        private const val KEY_PENDING_ENABLE_OWNER = "pending_enable_owner_user_id"
        private const val KEY_RUNTIME = "runtime"
        private const val KEY_FOREGROUND_ASKED = "foreground_permission_requested"
        private const val KEY_BACKGROUND_ASKED = "background_permission_requested"
        private const val KEY_LAST_FIX_AT = "last_fix_at_millis"
        private const val KEY_LAST_ACCURACY = "last_accuracy_meters"
    }
}
