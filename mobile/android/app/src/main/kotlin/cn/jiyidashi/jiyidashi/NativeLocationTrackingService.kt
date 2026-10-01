package cn.jiyidashi.jiyidashi

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.IBinder
import java.util.UUID

class NativeLocationTrackingService : Service(), LocationListener {
    private lateinit var locationManager: LocationManager
    private lateinit var store: NativeLocationStore

    override fun onCreate() {
        super.onCreate()
        locationManager = getSystemService(LOCATION_SERVICE) as LocationManager
        store = NativeLocationStore(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val ownerUserId = intent?.getStringExtra(EXTRA_OWNER_USER_ID)?.trim().orEmpty()
        if (ownerUserId.isEmpty()) {
            // START_STICKY process recreation arrives without the original intent. The OS
            // may recreate the foreground service, but that is not Privacy/Auth authority
            // to collect a single coordinate. Keep a visible foreground quarantine only,
            // persist recovery_pending, and let the headless coordinator prove AUTH+Privacy.
            val enabledOwner = store.enabledOwnerUserId?.trim().orEmpty()
            if (enabledOwner.isEmpty()) {
                stopProduction(NativeLocationRuntimeState.STOPPED)
                return START_NOT_STICKY
            }
            return startRecoveryQuarantine(enabledOwner)
        }

        if (intent?.action == ACTION_UPDATE_SAMPLING) {
            if (isActive && store.activeOwnerUserId == ownerUserId) {
                requestAdaptiveUpdates(store.samplingProfile(ownerUserId))
            }
            return START_NOT_STICKY
        }

        val permission = AndroidLocationPermissions.level(this, store)
        if (
            !NativeLocationPolicy.canStart(
                ownerUserId = ownerUserId,
                enabledOwnerUserId = store.enabledOwnerUserId,
                permission = permission,
                locationServicesEnabled = AndroidLocationPermissions.locationServicesEnabled(this),
            )
        ) {
            // Service entry is a second fail-closed gate. The Flutter/native bridge cannot
            // force production if permission or account ownership changed between calls.
            stopProduction(NativeLocationRuntimeState.STOPPED)
            return START_NOT_STICKY
        }

        return try {
            createNotificationChannel()
            val notificationBuilder =
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    Notification.Builder(this, NOTIFICATION_CHANNEL_ID)
                } else {
                    @Suppress("DEPRECATION")
                    Notification.Builder(this)
                }
            startForeground(
                NOTIFICATION_ID,
                notificationBuilder
                    .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                    .setContentTitle("迹忆自动位置记忆")
                    .setContentText("已按你的授权在后台使用低频位置更新")
                    .setOngoing(true)
                    .build(),
            )

            store.activeOwnerUserId = ownerUserId
            store.runtime = NativeLocationRuntimeState.RUNNING
            store.clearRecoveryPending(ownerUserId)
            store.beginTracking(ownerUserId)
            isActive = true
            requestAdaptiveUpdates(store.samplingProfile(ownerUserId))
            START_STICKY
        } catch (_: SecurityException) {
            stopProduction(NativeLocationRuntimeState.STOPPED)
            START_NOT_STICKY
        } catch (_: IllegalStateException) {
            stopProduction(NativeLocationRuntimeState.STOPPED)
            START_NOT_STICKY
        }
    }

    private fun startRecoveryQuarantine(ownerUserId: String): Int {
        return try {
            createNotificationChannel()
            val notificationBuilder =
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    Notification.Builder(this, NOTIFICATION_CHANNEL_ID)
                } else {
                    @Suppress("DEPRECATION")
                    Notification.Builder(this)
                }
            startForeground(
                NOTIFICATION_ID,
                notificationBuilder
                    .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                    .setContentTitle("迹忆自动位置记忆")
                    .setContentText("正在安全恢复自动记录")
                    .setOngoing(true)
                    .build(),
            )

            try {
                locationManager.removeUpdates(this)
            } catch (_: SecurityException) {
                // Quarantine remains non-producing even if permission changed.
            }
            isActive = false
            store.finishTracking(ownerUserId)
            store.activeOwnerUserId = null
            store.runtime = NativeLocationRuntimeState.STOPPED
            store.markRecoveryPending(ownerUserId, "service_recreated")
            PassiveMemoryRecoveryScheduler.ensurePeriodic(this)
            PassiveMemoryRecoveryScheduler.schedule(
                this,
                reason = "service_recreated",
                markProducerRecovery = true,
            )
            START_STICKY
        } catch (_: RuntimeException) {
            stopProduction(NativeLocationRuntimeState.STOPPED)
            START_NOT_STICKY
        }
    }

    /**
     * Android can honor both cadence and distance at the provider boundary. Profiles never go
     * below 15 seconds, so P cannot regress into a fixed 5-second wake loop.
     */
    private fun requestAdaptiveUpdates(profile: NativeSamplingProfile) {
        try {
            locationManager.removeUpdates(this)
        } catch (_: SecurityException) {
            return
        }
        val enabledProviders = locationManager.getProviders(true)
        val providers = listOf(
            LocationManager.PASSIVE_PROVIDER,
            LocationManager.NETWORK_PROVIDER,
            LocationManager.GPS_PROVIDER,
        ).filter { enabledProviders.contains(it) }

        for (provider in providers) {
            locationManager.requestLocationUpdates(
                provider,
                profile.minIntervalMs,
                profile.minDistanceMeters,
                this,
            )
        }
    }

    override fun onLocationChanged(location: Location) {
        val ownerUserId = store.activeOwnerUserId ?: return
        if (store.runtime != NativeLocationRuntimeState.RUNNING) return

        store.recordWakeup(ownerUserId)
        val recordedAtMillis =
            location.time.takeIf { it > 0L } ?: System.currentTimeMillis()
        val accuracy = NativeMotionSignalMapper.normalizedAccuracy(
            location.hasAccuracy(),
            location.accuracy,
        )
        val speed = NativeMotionSignalMapper.normalizedSpeed(
            location.hasSpeed(),
            location.speed,
        )

        store.lastFixAtMillis = recordedAtMillis
        store.lastAccuracyMeters = accuracy

        val profile = store.samplingProfile(ownerUserId)
        // [人工注释][S2-004/005] Publish only quality/motion metadata before the raw GPS gate.
        // This makes adaptive backoff reachable without persisting a rejected coordinate.
        store.setLatestMotionObservation(
            NativeMotionObservation(
                ownerUserId = ownerUserId,
                accuracyMeters = accuracy,
                speedMetersPerSecond = speed,
                recordedAtMillis = recordedAtMillis,
            ),
        )
        if (!NativeLocationSampleAdmission.accepts(accuracy, profile) ||
            !NativeLocationSampleAdmission.cadenceAllows(
                previousRecordedAtMillis = store.lastQueuedAtMillis(ownerUserId),
                candidateRecordedAtMillis = recordedAtMillis,
                minIntervalMs = profile.minIntervalMs,
            )
        ) {
            store.recordSampleDropped(ownerUserId)
            NativeLocationPlugin.notifySamplesAvailable()
            return
        }

        val queued = store.enqueueLocationSample(
            NativeQueuedLocationSample(
                ownerUserId = ownerUserId,
                clientUuid = UUID.randomUUID().toString(),
                latitude = location.latitude,
                longitude = location.longitude,
                accuracyMeters = accuracy,
                speedMetersPerSecond = speed,
                recordedAtMillis = recordedAtMillis,
            ),
        )
        if (queued) {
            store.setLastQueuedAtMillis(ownerUserId, recordedAtMillis)
            store.recordSampleAccepted(ownerUserId)
        } else {
            // A full/corrupt durable native queue is measurable backpressure, never an
            // invitation to overwrite older unsent points.
            store.recordSampleDropped(ownerUserId)
        }
        val flutterListenerPresent = NativeLocationPlugin.notifySamplesAvailable()
        if (!flutterListenerPresent) {
            // No Flutter UI/engine is alive. Schedule one bounded, network-constrained
            // batch wake-up instead of starting an isolate per GPS point.
            PassiveMemoryRecoveryScheduler.schedule(
                this,
                reason = if (queued) "native_backlog" else "native_backpressure",
                markProducerRecovery = false,
                initialDelayMinutes = if (queued) 15 else 0,
            )
        }
    }

    override fun onProviderDisabled(provider: String) {
        if (!AndroidLocationPermissions.locationServicesEnabled(this)) {
            stopProduction(NativeLocationRuntimeState.STOPPED)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        val owner = store.activeOwnerUserId
        if (owner != null &&
            store.enabledOwnerUserId == owner &&
            store.runtime == NativeLocationRuntimeState.RUNNING
        ) {
            // The FGS may continue after the task is swiped. Schedule delivery only; do not
            // claim producer recovery while a real native producer is still active.
            PassiveMemoryRecoveryScheduler.schedule(
                this,
                reason = "task_removed",
                markProducerRecovery = false,
            )
        }
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        try {
            locationManager.removeUpdates(this)
        } catch (_: SecurityException) {
            // Permission revocation may race service teardown; removing updates is best-effort.
        }
        val ownerUserId = store.activeOwnerUserId
        val unexpectedStop =
            ownerUserId != null &&
                store.enabledOwnerUserId == ownerUserId &&
                store.runtime == NativeLocationRuntimeState.RUNNING
        if (ownerUserId != null) {
            store.finishTracking(ownerUserId)
        }
        isActive = false
        store.activeOwnerUserId = null
        if (store.runtime == NativeLocationRuntimeState.RUNNING) {
            store.runtime = NativeLocationRuntimeState.STOPPED
        }
        if (unexpectedStop) {
            PassiveMemoryRecoveryScheduler.schedule(
                this,
                reason = "service_destroyed",
                markProducerRecovery = true,
            )
        }
        super.onDestroy()
    }

    private fun stopProduction(runtime: NativeLocationRuntimeState) {
        try {
            locationManager.removeUpdates(this)
        } catch (_: SecurityException) {
            // A revoked permission must still converge to stopped.
        }
        val ownerUserId = store.activeOwnerUserId
        if (ownerUserId != null) {
            store.finishTracking(ownerUserId)
        }
        isActive = false
        store.activeOwnerUserId = null
        store.runtime = runtime
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        stopSelf()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(
                NOTIFICATION_CHANNEL_ID,
                "自动位置记忆",
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
    }

    companion object {
        const val EXTRA_OWNER_USER_ID = "owner_user_id"
        const val ACTION_UPDATE_SAMPLING =
            "cn.jiyidashi.jiyidashi.action.UPDATE_LOCATION_SAMPLING"

        private const val NOTIFICATION_CHANNEL_ID = "native_location_tracking"
        private const val NOTIFICATION_ID = 2301

        @Volatile
        var isActive: Boolean = false
            private set
    }
}
