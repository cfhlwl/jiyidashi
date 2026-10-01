package cn.jiyidashi.jiyidashi

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
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
        val requestBuilder = OneTimeWorkRequestBuilder<PassiveMemoryRecoveryWorker>()
            .setConstraints(constraints)
            .setInputData(workDataOf(PassiveMemoryRecoveryWorker.KEY_REASON to reason))
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
        if (store.enabledOwnerUserId.isNullOrBlank()) {
            return Result.success(workDataOf("status" to "automatic_disabled"))
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
        return if (retry) {
            Result.retry()
        } else {
            Result.success(
                workDataOf(
                    "status" to status,
                    "reason" to (inputData.getString(KEY_REASON) ?: "unknown"),
                ),
            )
        }
    }

    companion object {
        const val KEY_REASON = "reason"
        private const val COMPLETION_CHANNEL = "cn.jiyidashi/passive_recovery"
        private const val DART_ENTRYPOINT = "passiveMemoryRecoveryMain"
        private const val MAX_RUNTIME_SECONDS = 90L
    }
}
