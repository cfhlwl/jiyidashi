package cn.jiyidashi.jiyidashi

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import io.flutter.FlutterInjector
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.dart.DartExecutor
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Schedules authority-aware recovery only. It never starts the location FGS directly.
 *
 * The persisted enabled owner is merely a local recovery hint used to avoid pointless work.
 * The headless Dart isolate must still restore AUTH-001 and read fresh server Privacy before
 * [NativeLocationPlugin.start] can run.
 */
object PassiveMemoryRecoveryScheduler {
    private const val UNIQUE_WORK = "jiyidashi-passive-memory-recovery"
    private const val PERIODIC_WORK = "jiyidashi-passive-memory-watchdog"

    fun ensurePeriodic(context: Context) {
        val appContext = context.applicationContext
        val store = NativeLocationStore(appContext)
        if (store.enabledOwnerUserId.isNullOrBlank()) return

        val request = PeriodicWorkRequest.Builder(
            PassiveMemoryRecoveryWorker::class.java,
            15,
            TimeUnit.MINUTES,
        )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setInputData(
                Data.Builder()
                    .putString(PassiveMemoryRecoveryWorker.KEY_REASON, "periodic_watchdog")
                    .build(),
            )
            .build()

        WorkManager.getInstance(appContext).enqueueUniquePeriodicWork(
            PERIODIC_WORK,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    fun cancelPeriodic(context: Context) {
        WorkManager.getInstance(context.applicationContext)
            .cancelUniqueWork(PERIODIC_WORK)
    }

    fun schedule(
        context: Context,
        reason: String,
        markProducerRecovery: Boolean = true,
        initialDelayMinutes: Long = 0,
    ) {
        val appContext = context.applicationContext
        val store = NativeLocationStore(appContext)
        val enabledOwner = store.enabledOwnerUserId?.trim().orEmpty()
        if (enabledOwner.isEmpty()) return

        if (markProducerRecovery) {
            store.markRecoveryPending(enabledOwner, reason)
        }

        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val requestBuilder = OneTimeWorkRequest.Builder(
            PassiveMemoryRecoveryWorker::class.java,
        )
            .setConstraints(constraints)
            .setInputData(
                Data.Builder()
                    .putString(PassiveMemoryRecoveryWorker.KEY_REASON, reason)
                    .build(),
            )
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                15,
                TimeUnit.MINUTES,
            )
        if (initialDelayMinutes > 0) {
            requestBuilder.setInitialDelay(initialDelayMinutes, TimeUnit.MINUTES)
        }
        val request = requestBuilder.build()

        WorkManager.getInstance(appContext).enqueueUniqueWork(
            UNIQUE_WORK,
            ExistingWorkPolicy.KEEP,
            request,
        )
    }
}

/**
 * Process-local arbitration between the normal Flutter engine and the headless worker.
 *
 * AUTH-001 refresh tokens rotate exactly once. Two Dart engines must therefore never
 * refresh the same persisted credential concurrently. Existing UI/background engines win;
 * if the worker wins first, a later normal app startup waits here before restoring session.
 */
object PassiveMemoryRecoveryProcessGate {
    private val lock = Any()
    private var headlessActive = false
    private val waiters = mutableListOf<MethodChannel.Result>()

    fun tryBeginHeadless(): Boolean = synchronized(lock) {
        if (headlessActive || NativeLocationPlugin.hasAttachedFlutterEngine()) {
            false
        } else {
            headlessActive = true
            true
        }
    }

    fun awaitIdle(result: MethodChannel.Result) {
        val completeNow = synchronized(lock) {
            if (!headlessActive) {
                true
            } else {
                waiters.add(result)
                false
            }
        }
        if (completeNow) {
            result.success(true)
        }
    }

    fun finishHeadless() {
        val pending = synchronized(lock) {
            headlessActive = false
            waiters.toList().also { waiters.clear() }
        }
        if (pending.isEmpty()) return
        Handler(Looper.getMainLooper()).post {
            pending.forEach { waiter ->
                try {
                    waiter.success(true)
                } catch (_: RuntimeException) {
                    // A waiting engine may have detached; no auth authority is granted here.
                }
            }
        }
    }
}

/**
 * Boot/package replacement are wake-up opportunities, not authorization events.
 *
 * We deliberately do not call startForegroundService() here. The receiver only persists a
 * recovery hint and asks WorkManager for a network-constrained headless authority check.
 */
class PassiveMemoryRecoveryReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val reason = when (intent?.action) {
            Intent.ACTION_BOOT_COMPLETED -> "boot_completed"
            Intent.ACTION_MY_PACKAGE_REPLACED -> "package_replaced"
            else -> return
        }

        val store = NativeLocationStore(context)
        val enabledOwner = store.enabledOwnerUserId?.trim().orEmpty()
        if (enabledOwner.isEmpty()) return

        // Any persisted RUNNING bit belongs to the pre-reboot/pre-replacement process and
        // cannot prove a live producer. Force truthful stopped state before scheduling.
        store.activeOwnerUserId = null
        store.runtime = NativeLocationRuntimeState.STOPPED
        PassiveMemoryRecoveryScheduler.ensurePeriodic(context)
        PassiveMemoryRecoveryScheduler.schedule(
            context,
            reason,
            markProducerRecovery = true,
        )
    }
}

/**
 * Runs the same Flutter AUTH-001/Privacy/delivery coordinator without creating AppShell/UI.
 */
class PassiveMemoryRecoveryWorker(
    appContext: Context,
    params: WorkerParameters,
) : Worker(appContext, params) {
    override fun doWork(): Result {
        val store = NativeLocationStore(applicationContext)
        val enabledOwner = store.enabledOwnerUserId?.trim().orEmpty()
        if (enabledOwner.isEmpty()) {
            PassiveMemoryRecoveryScheduler.cancelPeriodic(applicationContext)
            return Result.success(
                Data.Builder().putString("status", "automatic_disabled").build(),
            )
        }

        if (!PassiveMemoryRecoveryProcessGate.tryBeginHeadless()) {
            // A normal Flutter engine is already responsible for AUTH/session rotation and
            // native sample notifications. Starting a second isolate would create a refresh
            // replay race, so this watchdog run is intentionally a no-op.
            return Result.success(
                Data.Builder().putString("status", "flutter_engine_active").build(),
            )
        }

        return try {
            runClaimedHeadless(store, enabledOwner)
        } finally {
            PassiveMemoryRecoveryProcessGate.finishHeadless()
        }
    }

    private fun runClaimedHeadless(
        store: NativeLocationStore,
        enabledOwner: String,
    ): Result {
        // Android can kill the whole process without Service.onDestroy(). Persisted
        // RUNNING + matching active owner + no live service means only "eligible to recover",
        // never permission to restart. Dart still has to refresh AUTH-001 and server Privacy.
        if (NativeLocationPolicy.shouldRecoverAfterProcessDeath(
                enabledOwnerUserId = store.enabledOwnerUserId,
                activeOwnerUserId = store.activeOwnerUserId,
                runtime = store.runtime,
                nativeProducerActive = NativeLocationTrackingService.isActive,
            )
        ) {
            store.markRecoveryPending(enabledOwner, "process_recreated")
            store.activeOwnerUserId = null
            store.runtime = NativeLocationRuntimeState.STOPPED
        }

        val completion = CountDownLatch(1)
        val handler = Handler(Looper.getMainLooper())
        var retry = true
        var status = "worker_setup_failed"
        var engine: FlutterEngine? = null

        handler.post {
            try {
                val loader = FlutterInjector.instance().flutterLoader()
                loader.startInitialization(applicationContext)
                loader.ensureInitializationComplete(applicationContext, null)

                val nextEngine = FlutterEngine(applicationContext)
                engine = nextEngine
                // Generated plugins are auto-registered by FlutterEngine. Native location is
                // intentionally manual because foreground Activity registration is optional.
                nextEngine.plugins.add(NativeLocationPlugin())

                MethodChannel(
                    nextEngine.dartExecutor.binaryMessenger,
                    COMPLETION_CHANNEL,
                ).setMethodCallHandler { call, result ->
                    if (call.method != "complete") {
                        result.notImplemented()
                        return@setMethodCallHandler
                    }
                    retry = call.argument<Boolean>("retry") == true
                    status = call.argument<String>("status") ?: "unknown"
                    result.success(null)
                    completion.countDown()
                }

                nextEngine.dartExecutor.executeDartEntrypoint(
                    DartExecutor.DartEntrypoint(
                        loader.findAppBundlePath(),
                        DART_ENTRYPOINT,
                    ),
                )
            } catch (_: Throwable) {
                retry = true
                status = "worker_setup_failed"
                completion.countDown()
            }
        }

        val completed = try {
            completion.await(MAX_RUNTIME_SECONDS, TimeUnit.SECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }

        handler.post {
            try {
                engine?.destroy()
            } catch (_: Throwable) {
                // Engine teardown must not turn an already completed authority check into
                // a false delivery success/failure.
            }
        }

        if (!completed) return Result.retry()

        if (status == "noSession" ||
            status == "accountDeletionInProgress" ||
            status == "authorityChanged"
        ) {
            // Loss of account/session publication authority is permission to STOP only.
            // Do not purge queued coordinates here: account deletion/logout local cleanup
            // owns deletion. But no stale native producer may continue collecting.
            sealAutomaticProduction(store, enabledOwner)
        }

        return if (retry) {
            Result.retry()
        } else {
            Result.success(
                Data.Builder()
                    .putString("status", status)
                    .putString("reason", inputData.getString(KEY_REASON) ?: "unknown")
                    .build(),
            )
        }
    }

    private fun sealAutomaticProduction(
        store: NativeLocationStore,
        ownerUserId: String,
    ) {
        store.finishTracking(ownerUserId)
        applicationContext.stopService(
            Intent(applicationContext, NativeLocationTrackingService::class.java),
        )
        store.clearAutomaticOwner(ownerUserId)
        store.clearRecoveryPending(ownerUserId)
        store.runtime = NativeLocationRuntimeState.STOPPED
        PassiveMemoryRecoveryScheduler.cancelPeriodic(applicationContext)
    }

    companion object {
        const val KEY_REASON = "reason"
        private const val COMPLETION_CHANNEL = "cn.jiyidashi/passive_recovery"
        private const val DART_ENTRYPOINT = "passiveMemoryRecoveryMain"
        private const val MAX_RUNTIME_SECONDS = 90L
    }
}
