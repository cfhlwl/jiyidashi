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
            stopProduction(NativeLocationRuntimeState.STOPPED)
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
            isActive = true
            requestLowFrequencyUpdates()
            START_NOT_STICKY
        } catch (_: SecurityException) {
            stopProduction(NativeLocationRuntimeState.STOPPED)
            START_NOT_STICKY
        } catch (_: IllegalStateException) {
            stopProduction(NativeLocationRuntimeState.STOPPED)
            START_NOT_STICKY
        }
    }

    /**
     * Foundation sampling intentionally uses minute/distance thresholds and passive/network
     * signals instead of a fixed high-frequency loop. Smart motion-aware sampling belongs to
     * S2-004/S2-005 and must not be smuggled into this foundation PR.
     */
    private fun requestLowFrequencyUpdates() {
        val enabledProviders = locationManager.getProviders(true)
        val providers = listOf(
            LocationManager.PASSIVE_PROVIDER,
            LocationManager.NETWORK_PROVIDER,
            LocationManager.GPS_PROVIDER,
        ).filter { enabledProviders.contains(it) }

        for (provider in providers) {
            locationManager.requestLocationUpdates(
                provider,
                MIN_UPDATE_INTERVAL_MS,
                MIN_UPDATE_DISTANCE_METERS,
                this,
            )
        }
    }

    override fun onLocationChanged(location: Location) {
        // No latitude/longitude is persisted in this foundation line. Until S2-006 defines
        // the owner-scoped sync/lifecycle contract, status keeps only non-location diagnostics.
        store.lastFixAtMillis = location.time.takeIf { it > 0L } ?: System.currentTimeMillis()
        store.lastAccuracyMeters = location.accuracy
    }

    override fun onProviderDisabled(provider: String) {
        if (!AndroidLocationPermissions.locationServicesEnabled(this)) {
            stopProduction(NativeLocationRuntimeState.STOPPED)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        try {
            locationManager.removeUpdates(this)
        } catch (_: SecurityException) {
            // Permission revocation may race service teardown; removing updates is best-effort.
        }
        isActive = false
        store.activeOwnerUserId = null
        if (store.runtime == NativeLocationRuntimeState.RUNNING) {
            store.runtime = NativeLocationRuntimeState.STOPPED
        }
        super.onDestroy()
    }

    private fun stopProduction(runtime: NativeLocationRuntimeState) {
        try {
            locationManager.removeUpdates(this)
        } catch (_: SecurityException) {
            // A revoked permission must still converge to stopped.
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

        private const val NOTIFICATION_CHANNEL_ID = "native_location_tracking"
        private const val NOTIFICATION_ID = 2301
        private const val MIN_UPDATE_INTERVAL_MS = 60_000L
        private const val MIN_UPDATE_DISTANCE_METERS = 50f

        @Volatile
        var isActive: Boolean = false
            private set
    }
}
