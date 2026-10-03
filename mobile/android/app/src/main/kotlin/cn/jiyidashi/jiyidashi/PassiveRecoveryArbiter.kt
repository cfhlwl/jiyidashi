package cn.jiyidashi.jiyidashi

/**
 * One process-wide authority arbiter shared by every Flutter engine in the Android app.
 *
 * WorkManager uses the app process (the manifest does not opt it into a separate process).
 * AUTH refresh credentials are single-use, so a headless recovery engine may only start
 * when no foreground Flutter engine is attached. Foreground startup may attach while a
 * claimed headless recovery is running, but it must wait for that recovery to release the
 * lease before restoring/refreshing the durable session.
 *
 * Keeping engine registration, headless claiming, and idle waiter registration behind the
 * same monitor closes the check-then-attach race that existed when attached-engine state was
 * read from a separate collection.
 */
internal class PassiveRecoveryArbiter<T> {
    private val lock = Any()
    private var headlessActive = false
    private var attachedEngineCount = 0
    private val idleWaiters = mutableListOf<T>()

    fun attachEngine() = synchronized(lock) {
        attachedEngineCount += 1
    }

    fun detachEngine() = synchronized(lock) {
        if (attachedEngineCount > 0) {
            attachedEngineCount -= 1
        }
    }

    fun tryBeginHeadless(): Boolean = synchronized(lock) {
        if (headlessActive || attachedEngineCount > 0) {
            false
        } else {
            headlessActive = true
            true
        }
    }

    /**
     * Returns true when the caller can continue immediately.
     * Otherwise the waiter is retained and returned exactly once by [finishHeadless].
     */
    fun awaitIdle(waiter: T): Boolean = synchronized(lock) {
        if (!headlessActive) {
            true
        } else {
            idleWaiters.add(waiter)
            false
        }
    }

    fun finishHeadless(): List<T> = synchronized(lock) {
        headlessActive = false
        idleWaiters.toList().also { idleWaiters.clear() }
    }

    internal fun snapshot(): Snapshot = synchronized(lock) {
        Snapshot(
            headlessActive = headlessActive,
            attachedEngineCount = attachedEngineCount,
            waiterCount = idleWaiters.size,
        )
    }

    internal data class Snapshot(
        val headlessActive: Boolean,
        val attachedEngineCount: Int,
        val waiterCount: Int,
    )
}
