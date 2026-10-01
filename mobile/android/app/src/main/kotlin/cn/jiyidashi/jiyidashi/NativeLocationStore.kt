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

    var recoveryPendingOwnerUserId: String?
        get() = prefs.getString(KEY_RECOVERY_PENDING_OWNER, null)
        private set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_RECOVERY_PENDING_OWNER)
                else putString(KEY_RECOVERY_PENDING_OWNER, value)
            }.commit()
        }

    fun markRecoveryPending(ownerUserId: String, reason: String) {
        recoveryPendingOwnerUserId = ownerUserId
        prefs.edit()
            .putString(KEY_RECOVERY_PENDING_REASON, reason)
            .putLong(KEY_RECOVERY_PENDING_AT, System.currentTimeMillis())
            .commit()
    }

    fun clearRecoveryPending(ownerUserId: String) {
        if (recoveryPendingOwnerUserId != ownerUserId) return
        prefs.edit()
            .remove(KEY_RECOVERY_PENDING_OWNER)
            .remove(KEY_RECOVERY_PENDING_REASON)
            .remove(KEY_RECOVERY_PENDING_AT)
            .commit()
    }

    fun recoveryReason(ownerUserId: String): String? =
        if (recoveryPendingOwnerUserId == ownerUserId) {
            prefs.getString(KEY_RECOVERY_PENDING_REASON, null)
        } else {
            null
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

    fun enqueueLocationSample(sample: NativeQueuedLocationSample): Boolean = synchronized(QUEUE_LOCK) {
        val samples = readPendingSamples().toMutableList()
        if (queueCorrupt) return@synchronized false
        if (samples.any {
                it.ownerUserId == sample.ownerUserId &&
                    it.clientUuid == sample.clientUuid
            }
        ) {
            return@synchronized true
        }
        if (!NativeOwnerQueueQuota.hasCapacity(
                samples = samples,
                ownerUserId = sample.ownerUserId,
                maxPerOwner = MAX_PENDING_SAMPLES_PER_OWNER,
            )
        ) {
            recordCapacityDrop(sample.ownerUserId, "native_queue_capacity")
            return@synchronized false
        }
        val nextSequence = maxOf(
            prefs.getLong(KEY_NEXT_QUEUE_SEQUENCE, 1L),
            (samples.maxOfOrNull { it.queueSequence } ?: 0L) + 1L,
        )
        val persisted = sample.copy(
            queueSequence = nextSequence,
            enqueuedAtMillis = System.currentTimeMillis(),
            handoffAttemptCount = 0,
        )
        samples.add(persisted)
        if (!writePendingSamples(samples)) {
            markQueueCorrupt("native_queue_persist_failed")
            return@synchronized false
        }
        prefs.edit()
            .putLong(KEY_NEXT_QUEUE_SEQUENCE, nextSequence + 1L)
            .putLong(ownerKey(KEY_LAST_ENQUEUE_AT, sample.ownerUserId), persisted.enqueuedAtMillis)
            .commit()
        true
    }

    fun pendingLocationSamples(
        ownerUserId: String,
        limit: Int,
    ): List<NativeQueuedLocationSample> = synchronized(QUEUE_LOCK) {
        val samples = readPendingSamples()
        if (queueCorrupt) return@synchronized emptyList()
        val selectedSequences = samples
            .asSequence()
            .filter { it.ownerUserId == ownerUserId }
            .take(limit.coerceIn(1, 500))
            .map { it.queueSequence }
            .toSet()
        if (selectedSequences.isEmpty()) return@synchronized emptyList()
        val updated = samples.map { sample ->
            if (selectedSequences.contains(sample.queueSequence)) {
                sample.copy(handoffAttemptCount = sample.handoffAttemptCount + 1)
            } else {
                sample
            }
        }
        if (!writePendingSamples(updated)) {
            markQueueCorrupt("native_queue_persist_failed")
            return@synchronized emptyList()
        }
        updated.filter { selectedSequences.contains(it.queueSequence) }
    }

    fun acknowledgeLocationSamples(
        ownerUserId: String,
        clientUuids: Set<String>,
    ) = synchronized(QUEUE_LOCK) {
        if (clientUuids.isEmpty()) return@synchronized
        val retained = readPendingSamples().filterNot {
            it.ownerUserId == ownerUserId && clientUuids.contains(it.clientUuid)
        }
        if (!queueCorrupt && !writePendingSamples(retained)) {
            markQueueCorrupt("native_queue_persist_failed")
        }
    }

    fun purgeLocationSamplingOwner(ownerUserId: String) = synchronized(QUEUE_LOCK) {
        if (queueCorrupt) {
            // Account deletion is privacy-authoritative. A corrupt mixed-owner payload
            // cannot be safely filtered, so remove the entire raw queue rather than risk
            // retaining the deleting owner's precise locations.
            prefs.edit()
                .remove(KEY_PENDING_SAMPLES)
                .remove(KEY_QUEUE_CORRUPT)
                .remove(KEY_QUEUE_CORRUPT_REASON)
                .remove(KEY_QUEUE_CORRUPT_AT)
                .putInt(KEY_QUEUE_SCHEMA_VERSION, NATIVE_QUEUE_SCHEMA_VERSION)
                .commit()
        } else {
            val retained = readPendingSamples().filterNot {
                it.ownerUserId == ownerUserId
            }
            if (!writePendingSamples(retained)) {
                markQueueCorrupt("native_queue_persist_failed")
            }
        }
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
            .remove(ownerKey(KEY_LAST_ENQUEUE_AT, ownerUserId))
            .remove(ownerKey(KEY_LAST_DELIVERY_AT, ownerUserId))
            .remove(ownerKey(KEY_DELIVERY_FAILURE_COUNT, ownerUserId))
            .remove(ownerKey(KEY_LAST_DELIVERY_FAILURE_AT, ownerUserId))
            .remove(ownerKey(KEY_LAST_DELIVERY_FAILURE_REASON, ownerUserId))
            .remove(ownerKey(KEY_CAPACITY_DROP_COUNT, ownerUserId))
            .remove(ownerKey(KEY_LAST_DROP_AT, ownerUserId))
            .remove(ownerKey(KEY_LAST_DROP_REASON, ownerUserId))
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

    fun recordCapacityDrop(
        ownerUserId: String,
        reason: String,
        nowMillis: Long = System.currentTimeMillis(),
    ) {
        increment(ownerUserId, KEY_CAPACITY_DROP_COUNT, 1L)
        prefs.edit()
            .putLong(ownerKey(KEY_LAST_DROP_AT, ownerUserId), nowMillis)
            .putString(ownerKey(KEY_LAST_DROP_REASON, ownerUserId), reason)
            .commit()
    }

    fun recordDeliveryFailure(
        ownerUserId: String,
        reason: String,
        nowMillis: Long = System.currentTimeMillis(),
    ) {
        increment(ownerUserId, KEY_DELIVERY_FAILURE_COUNT, 1L)
        prefs.edit()
            .putLong(ownerKey(KEY_LAST_DELIVERY_FAILURE_AT, ownerUserId), nowMillis)
            .putString(ownerKey(KEY_LAST_DELIVERY_FAILURE_REASON, ownerUserId), reason)
            .commit()
    }

    fun recordUploadBatch(ownerUserId: String, sampleCount: Int) {
        if (sampleCount <= 0) return
        increment(ownerUserId, KEY_METRIC_UPLOAD_BATCHES, 1L)
        increment(ownerUserId, KEY_METRIC_UPLOADED_SAMPLES, sampleCount.toLong())
        prefs.edit()
            .putLong(ownerKey(KEY_LAST_DELIVERY_AT, ownerUserId), System.currentTimeMillis())
            .commit()
    }

    fun queueDiagnostics(ownerUserId: String): Map<String, Any?> =
        synchronized(QUEUE_LOCK) {
        val samples = readPendingSamples().filter { it.ownerUserId == ownerUserId }
        val oldest = samples.minOfOrNull { it.enqueuedAtMillis }
        val lastEnqueueKey = ownerKey(KEY_LAST_ENQUEUE_AT, ownerUserId)
        val lastDeliveryKey = ownerKey(KEY_LAST_DELIVERY_AT, ownerUserId)
        val lastDropKey = ownerKey(KEY_LAST_DROP_AT, ownerUserId)
        val lastFailureKey = ownerKey(KEY_LAST_DELIVERY_FAILURE_AT, ownerUserId)
        val depth = samples.size
        mapOf(
            "queue_schema_version" to NATIVE_QUEUE_SCHEMA_VERSION,
            "queue_depth" to depth,
            "queue_capacity" to MAX_PENDING_SAMPLES_PER_OWNER,
            "oldest_pending_at_millis" to oldest,
            "last_enqueue_at_millis" to if (prefs.contains(lastEnqueueKey)) {
                prefs.getLong(lastEnqueueKey, 0L)
            } else {
                null
            },
            "last_delivery_at_millis" to if (prefs.contains(lastDeliveryKey)) {
                prefs.getLong(lastDeliveryKey, 0L)
            } else {
                null
            },
            "delivery_failure_count" to metric(ownerUserId, KEY_DELIVERY_FAILURE_COUNT),
            "last_delivery_failure_at_millis" to if (prefs.contains(lastFailureKey)) {
                prefs.getLong(lastFailureKey, 0L)
            } else {
                null
            },
            "last_delivery_failure_reason" to
                prefs.getString(ownerKey(KEY_LAST_DELIVERY_FAILURE_REASON, ownerUserId), null),
            "capacity_pressure" to depth >= CAPACITY_PRESSURE_THRESHOLD,
            "dropped_sample_count" to metric(ownerUserId, KEY_CAPACITY_DROP_COUNT),
            "last_drop_at_millis" to if (prefs.contains(lastDropKey)) {
                prefs.getLong(lastDropKey, 0L)
            } else {
                null
            },
            "last_drop_reason" to prefs.getString(ownerKey(KEY_LAST_DROP_REASON, ownerUserId), null),
            "queue_corrupt" to queueCorrupt,
            "queue_corrupt_reason" to prefs.getString(KEY_QUEUE_CORRUPT_REASON, null),
        )
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

    private val queueCorrupt: Boolean
        get() = prefs.getBoolean(KEY_QUEUE_CORRUPT, false)

    private fun markQueueCorrupt(reason: String) {
        prefs.edit()
            .putBoolean(KEY_QUEUE_CORRUPT, true)
            .putString(KEY_QUEUE_CORRUPT_REASON, reason)
            .putLong(KEY_QUEUE_CORRUPT_AT, System.currentTimeMillis())
            .commit()
    }

    private fun readPendingSamples(): List<NativeQueuedLocationSample> {
        if (queueCorrupt) return emptyList()
        val raw = prefs.getString(KEY_PENDING_SAMPLES, "[]") ?: "[]"
        return try {
            val array = JSONArray(raw)
            val parsed = buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    val owner = item.getString("owner_user_id").trim()
                    val uuid = item.getString("client_uuid").trim()
                    require(owner.isNotEmpty() && uuid.isNotEmpty())
                    val recordedAt = item.getLong("recorded_at_millis")
                    val latitude = item.getDouble("latitude")
                    val longitude = item.getDouble("longitude")
                    require(latitude in -90.0..90.0 && longitude in -180.0..180.0)
                    add(
                        NativeQueuedLocationSample(
                            ownerUserId = owner,
                            clientUuid = uuid,
                            latitude = latitude,
                            longitude = longitude,
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
                            recordedAtMillis = recordedAt,
                            queueSequence = item.optLong("queue_sequence", 0L),
                            enqueuedAtMillis =
                                item.optLong("enqueued_at_millis", recordedAt),
                            handoffAttemptCount =
                                item.optInt("handoff_attempt_count", 0).coerceAtLeast(0),
                        ),
                    )
                }
            }
            val requiresMigration =
                prefs.getInt(KEY_QUEUE_SCHEMA_VERSION, 1) < NATIVE_QUEUE_SCHEMA_VERSION ||
                    parsed.any { it.queueSequence <= 0L }
            if (!requiresMigration) {
                parsed
            } else {
                var next = 1L
                val migrated = parsed.map { sample ->
                    val sequence = if (sample.queueSequence > 0L) {
                        sample.queueSequence
                    } else {
                        next
                    }
                    next = maxOf(next, sequence + 1L)
                    sample.copy(
                        queueSequence = sequence,
                        enqueuedAtMillis = sample.enqueuedAtMillis.takeIf { it > 0L }
                            ?: sample.recordedAtMillis,
                    )
                }
                if (!writePendingSamples(migrated)) {
                    markQueueCorrupt("native_queue_migration_persist_failed")
                    emptyList()
                } else {
                    prefs.edit()
                        .putInt(KEY_QUEUE_SCHEMA_VERSION, NATIVE_QUEUE_SCHEMA_VERSION)
                        .putLong(KEY_NEXT_QUEUE_SEQUENCE, next)
                        .commit()
                    migrated
                }
            }
        } catch (_: Exception) {
            // Do not reinterpret a malformed durable queue as an empty queue and overwrite it.
            // The original raw payload remains stored for diagnostics/recovery.
            markQueueCorrupt("native_queue_decode_failed")
            emptyList()
        }
    }

    private fun writePendingSamples(samples: List<NativeQueuedLocationSample>): Boolean {
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
                    .put("recorded_at_millis", sample.recordedAtMillis)
                    .put("queue_sequence", sample.queueSequence)
                    .put("enqueued_at_millis", sample.enqueuedAtMillis)
                    .put("handoff_attempt_count", sample.handoffAttemptCount),
            )
        }
        return prefs.edit()
            .putString(KEY_PENDING_SAMPLES, array.toString())
            .putInt(KEY_QUEUE_SCHEMA_VERSION, NATIVE_QUEUE_SCHEMA_VERSION)
            .commit()
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
        private const val KEY_RECOVERY_PENDING_OWNER = "recovery_pending_owner_user_id"
        private const val KEY_RECOVERY_PENDING_REASON = "recovery_pending_reason"
        private const val KEY_RECOVERY_PENDING_AT = "recovery_pending_at"
        private const val KEY_RUNTIME = "runtime"
        private const val KEY_FOREGROUND_ASKED = "foreground_permission_requested"
        private const val KEY_BACKGROUND_ASKED = "background_permission_requested"
        private const val KEY_LAST_FIX_AT = "last_fix_at_millis"
        private const val KEY_LAST_ACCURACY = "last_accuracy_meters"
        private const val KEY_PENDING_SAMPLES = "pending_location_samples_json"
        private const val KEY_QUEUE_SCHEMA_VERSION = "pending_location_samples_schema_version"
        private const val KEY_NEXT_QUEUE_SEQUENCE = "pending_location_samples_next_sequence"
        private const val KEY_QUEUE_CORRUPT = "pending_location_samples_corrupt"
        private const val KEY_QUEUE_CORRUPT_REASON = "pending_location_samples_corrupt_reason"
        private const val KEY_QUEUE_CORRUPT_AT = "pending_location_samples_corrupt_at"
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
        private const val KEY_LAST_ENQUEUE_AT = "last_enqueue_at"
        private const val KEY_LAST_DELIVERY_AT = "last_delivery_at"
        private const val KEY_DELIVERY_FAILURE_COUNT = "delivery_failure_count"
        private const val KEY_LAST_DELIVERY_FAILURE_AT = "last_delivery_failure_at"
        private const val KEY_LAST_DELIVERY_FAILURE_REASON = "last_delivery_failure_reason"
        private const val KEY_CAPACITY_DROP_COUNT = "capacity_drop_count"
        private const val KEY_LAST_DROP_AT = "last_drop_at"
        private const val KEY_LAST_DROP_REASON = "last_drop_reason"
        private val QUEUE_LOCK = Any()

        private const val NATIVE_QUEUE_SCHEMA_VERSION = 2
        private const val MAX_PENDING_SAMPLES_PER_OWNER = 1000
        private const val CAPACITY_PRESSURE_THRESHOLD = 800
    }
}
