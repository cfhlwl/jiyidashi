package cn.jiyidashi.jiyidashi

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

// 这是设备本地的 owner-scoped 采样/运行状态持久层，不是服务器授权来源。
// owner ID 只用于隔离队列、采样 profile 与指标；真正的账号权限和隐私 gate 仍由上层认证/控制器决定。
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

    fun samplingProfile(ownerUserId: String): NativeSamplingProfile {
        val raw = prefs.getString(ownerKey(KEY_SAMPLING_PROFILE, ownerUserId), null)
            ?: return NativeSamplingProfile.DEFAULT
        return try {
            val json = JSONObject(raw)
            NativeSamplingProfile.validated(
                motionState = NativeMotionState.fromWire(json.optString("motion_state")),
                minIntervalMs = json.optLong("min_interval_ms", 120_000L),
                minDistanceMeters = json.optDouble("min_distance_m", 75.0),
                maxAccuracyMeters = json.optDouble("max_accuracy_m", 120.0),
            ) ?: NativeSamplingProfile.DEFAULT
        } catch (_: Exception) {
            NativeSamplingProfile.DEFAULT
        }
    }

    fun setSamplingProfile(ownerUserId: String, profile: NativeSamplingProfile) {
        val json = JSONObject()
            .put("motion_state", profile.motionState.wireValue)
            .put("min_interval_ms", profile.minIntervalMs)
            .put("min_distance_m", profile.minDistanceMeters.toDouble())
            .put("max_accuracy_m", profile.maxAccuracyMeters.toDouble())
        prefs.edit()
            .putString(ownerKey(KEY_SAMPLING_PROFILE, ownerUserId), json.toString())
            .apply()
    }

    @Synchronized
    fun setLatestMotionObservation(observation: NativeMotionObservation) {
        // Quality/motion observation intentionally excludes latitude/longitude: a poor raw fix may be
        // rejected while its coordinate-free quality signal survives for adaptive sampling decisions.
        val json = JSONObject()
            .put("accuracy", observation.accuracyMeters ?: JSONObject.NULL)
            .put("speed", observation.speedMetersPerSecond ?: JSONObject.NULL)
            .put("recorded_at_millis", observation.recordedAtMillis)
        prefs.edit()
            .putString(
                ownerKey(KEY_LATEST_MOTION_OBSERVATION, observation.ownerUserId),
                json.toString(),
            )
            .apply()
    }

    @Synchronized
    fun takeLatestMotionObservation(ownerUserId: String): NativeMotionObservation? {
        val key = ownerKey(KEY_LATEST_MOTION_OBSERVATION, ownerUserId)
        val raw = prefs.getString(key, null) ?: return null
        prefs.edit().remove(key).apply()
        return try {
            val json = JSONObject(raw)
            NativeMotionObservation(
                ownerUserId = ownerUserId,
                accuracyMeters = if (json.isNull("accuracy")) null else json.getDouble("accuracy").toFloat(),
                speedMetersPerSecond = if (json.isNull("speed")) null else json.getDouble("speed").toFloat(),
                recordedAtMillis = json.getLong("recorded_at_millis"),
            )
        } catch (_: Exception) {
            null
        }
    }

    @Synchronized
    fun enqueueLocationSample(sample: NativeQueuedLocationSample): Boolean {
        val samples = readPendingSamples().toMutableList()
        if (samples.any {
                it.ownerUserId == sample.ownerUserId &&
                    it.clientUuid == sample.clientUuid
            }
        ) {
            return true
        }
        if (!NativeOwnerQueueQuota.hasCapacity(
                samples = samples,
                ownerUserId = sample.ownerUserId,
                maxPerOwner = MAX_PENDING_SAMPLES_PER_OWNER,
            )
        ) {
            return false
        }
        samples.add(sample)
        writePendingSamples(samples)
        return true
    }

    @Synchronized
    fun pendingLocationSamples(
        ownerUserId: String,
        limit: Int,
    ): List<NativeQueuedLocationSample> =
        readPendingSamples()
            .asSequence()
            .filter { it.ownerUserId == ownerUserId }
            .take(limit.coerceIn(1, 500))
            .toList()

    @Synchronized
    fun acknowledgeLocationSamples(
        ownerUserId: String,
        clientUuids: Set<String>,
    ) {
        if (clientUuids.isEmpty()) return
        val retained = readPendingSamples().filterNot {
            it.ownerUserId == ownerUserId && clientUuids.contains(it.clientUuid)
        }
        writePendingSamples(retained)
    }

    @Synchronized
    fun purgeLocationSamplingOwner(ownerUserId: String) {
        val retained = readPendingSamples().filterNot {
            it.ownerUserId == ownerUserId
        }
        writePendingSamples(retained)
        prefs.edit()
            .remove(ownerKey(KEY_SAMPLING_PROFILE, ownerUserId))
            .remove(ownerKey(KEY_LATEST_MOTION_OBSERVATION, ownerUserId))
            .remove(ownerKey(KEY_METRIC_WAKEUPS, ownerUserId))
            .remove(ownerKey(KEY_METRIC_ACCEPTED, ownerUserId))
            .remove(ownerKey(KEY_METRIC_DROPPED, ownerUserId))
            .remove(ownerKey(KEY_METRIC_UPLOAD_BATCHES, ownerUserId))
            .remove(ownerKey(KEY_METRIC_UPLOADED_SAMPLES, ownerUserId))
            .remove(ownerKey(KEY_METRIC_ACTIVE_MS, ownerUserId))
            .remove(ownerKey(KEY_TRACKING_STARTED_AT, ownerUserId))
            .remove(ownerKey(KEY_LAST_QUEUED_AT, ownerUserId))
            .apply()
    }

    fun lastQueuedAtMillis(ownerUserId: String): Long? {
        val key = ownerKey(KEY_LAST_QUEUED_AT, ownerUserId)
        return if (prefs.contains(key)) prefs.getLong(key, 0L) else null
    }

    fun setLastQueuedAtMillis(ownerUserId: String, value: Long) {
        prefs.edit().putLong(ownerKey(KEY_LAST_QUEUED_AT, ownerUserId), value).apply()
    }

    fun recordWakeup(ownerUserId: String) {
        increment(ownerUserId, KEY_METRIC_WAKEUPS, 1L)
    }

    fun recordSampleAccepted(ownerUserId: String) {
        increment(ownerUserId, KEY_METRIC_ACCEPTED, 1L)
    }

    fun recordSampleDropped(ownerUserId: String) {
        increment(ownerUserId, KEY_METRIC_DROPPED, 1L)
    }

    fun recordUploadBatch(ownerUserId: String, sampleCount: Int) {
        if (sampleCount <= 0) return
        increment(ownerUserId, KEY_METRIC_UPLOAD_BATCHES, 1L)
        increment(ownerUserId, KEY_METRIC_UPLOADED_SAMPLES, sampleCount.toLong())
    }

    fun beginTracking(ownerUserId: String, nowMillis: Long = System.currentTimeMillis()) {
        val key = ownerKey(KEY_TRACKING_STARTED_AT, ownerUserId)
        if (!prefs.contains(key)) {
            prefs.edit().putLong(key, nowMillis).apply()
        }
    }

    fun finishTracking(ownerUserId: String, nowMillis: Long = System.currentTimeMillis()) {
        val key = ownerKey(KEY_TRACKING_STARTED_AT, ownerUserId)
        if (!prefs.contains(key)) return
        val started = prefs.getLong(key, nowMillis)
        val elapsed = (nowMillis - started).coerceAtLeast(0L)
        val activeKey = ownerKey(KEY_METRIC_ACTIVE_MS, ownerUserId)
        val accumulated = prefs.getLong(activeKey, 0L)
        prefs.edit()
            .putLong(activeKey, accumulated + elapsed)
            .remove(key)
            .apply()
    }

    fun metrics(
        ownerUserId: String,
        nowMillis: Long = System.currentTimeMillis(),
    ): Map<String, Long> {
        val activeKey = ownerKey(KEY_METRIC_ACTIVE_MS, ownerUserId)
        var activeMs = prefs.getLong(activeKey, 0L)
        val startedKey = ownerKey(KEY_TRACKING_STARTED_AT, ownerUserId)
        if (prefs.contains(startedKey)) {
            val started = prefs.getLong(startedKey, nowMillis)
            activeMs += (nowMillis - started).coerceAtLeast(0L)
        }
        // Metrics deliberately contain only counters/duration; coordinates and timestamps
        // remain exclusively in the sample queue and are never copied into observability.
        return mapOf(
            "wakeups" to metric(ownerUserId, KEY_METRIC_WAKEUPS),
            "samples_accepted" to metric(ownerUserId, KEY_METRIC_ACCEPTED),
            "samples_dropped" to metric(ownerUserId, KEY_METRIC_DROPPED),
            "upload_batches" to metric(ownerUserId, KEY_METRIC_UPLOAD_BATCHES),
            "uploaded_samples" to metric(ownerUserId, KEY_METRIC_UPLOADED_SAMPLES),
            "active_tracking_ms" to activeMs,
        )
    }

    private fun increment(ownerUserId: String, prefix: String, delta: Long) {
        val key = ownerKey(prefix, ownerUserId)
        prefs.edit().putLong(key, prefs.getLong(key, 0L) + delta).apply()
    }

    private fun metric(ownerUserId: String, prefix: String): Long =
        prefs.getLong(ownerKey(prefix, ownerUserId), 0L)

    private fun ownerKey(prefix: String, ownerUserId: String): String =
        "$prefix.$ownerUserId"

    private fun readPendingSamples(): List<NativeQueuedLocationSample> {
        val raw = prefs.getString(KEY_PENDING_SAMPLES, "[]") ?: "[]"
        return try {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.optJSONObject(index) ?: continue
                    val owner = item.optString("owner_user_id").trim()
                    val uuid = item.optString("client_uuid").trim()
                    if (owner.isEmpty() || uuid.isEmpty()) continue
                    add(
                        NativeQueuedLocationSample(
                            ownerUserId = owner,
                            clientUuid = uuid,
                            latitude = item.getDouble("latitude"),
                            longitude = item.getDouble("longitude"),
                            accuracyMeters = if (item.isNull("accuracy")) {
                                null
                            } else {
                                item.getDouble("accuracy").toFloat()
                            },
                            speedMetersPerSecond = if (item.isNull("speed")) {
                                null
                            } else {
                                item.getDouble("speed").toFloat()
                            },
                            recordedAtMillis = item.getLong("recorded_at_millis"),
                        ),
                    )
                }
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun writePendingSamples(samples: List<NativeQueuedLocationSample>) {
        val array = JSONArray()
        for (sample in samples) {
            array.put(
                JSONObject()
                    .put("owner_user_id", sample.ownerUserId)
                    .put("client_uuid", sample.clientUuid)
                    .put("latitude", sample.latitude)
                    .put("longitude", sample.longitude)
                    .put("accuracy", sample.accuracyMeters ?: JSONObject.NULL)
                    .put("speed", sample.speedMetersPerSecond ?: JSONObject.NULL)
                    .put("recorded_at_millis", sample.recordedAtMillis),
            )
        }
        prefs.edit().putString(KEY_PENDING_SAMPLES, array.toString()).apply()
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
        private const val KEY_PENDING_SAMPLES = "pending_location_samples_json"
        private const val KEY_SAMPLING_PROFILE = "sampling_profile"
        private const val KEY_LATEST_MOTION_OBSERVATION = "latest_motion_observation"
        private const val KEY_METRIC_WAKEUPS = "metric_wakeups"
        private const val KEY_METRIC_ACCEPTED = "metric_samples_accepted"
        private const val KEY_METRIC_DROPPED = "metric_samples_dropped"
        private const val KEY_METRIC_UPLOAD_BATCHES = "metric_upload_batches"
        private const val KEY_METRIC_UPLOADED_SAMPLES = "metric_uploaded_samples"
        private const val KEY_METRIC_ACTIVE_MS = "metric_active_tracking_ms"
        private const val KEY_TRACKING_STARTED_AT = "tracking_started_at"
        private const val KEY_LAST_QUEUED_AT = "last_queued_at"
        private const val MAX_PENDING_SAMPLES_PER_OWNER = 1000
    }
}
