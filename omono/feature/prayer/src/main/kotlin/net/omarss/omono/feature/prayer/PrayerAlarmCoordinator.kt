package net.omarss.omono.feature.prayer

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import timber.log.Timber
import java.time.LocalDate
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class PrayerAlarmCoordinator @Inject constructor(
    private val settings: PrayerSettingsRepository,
    private val locationCache: PrayerLocationCache,
    private val scheduler: PrayerScheduler,
    private val checkpoints: PrayerAlarmCheckpoints,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val mutex = Mutex()
    private var started = false

    @Synchronized
    fun start() {
        if (started) return
        started = true
        scope.launch {
            combine(settings.snapshot.distinctUntilChanged(), locationCache.last.distinctUntilChanged()) { _, _ -> Unit }
                .collect { repair("settings/location") }
        }
        scope.launch {
            while (true) {
                delay(60 * 60 * 1000L)
                repair("hourly check")
            }
        }
    }

    suspend fun repair(reason: String = "manual check") = mutex.withLock {
        try {
            val snapshot = settings.snapshot.first()
            val fix = locationCache.last.first()
            if (fix == null) {
                checkpoints.schedulingFailed("No saved location — open Prayer times and allow location")
                return@withLock
            }
            val today = LocalDate.now()
            val days = (0L..1L).map {
                PrayerTimesCalculator.computeDay(fix.latitude, fix.longitude, today.plusDays(it), snapshot)
            }
            checkpoints.scheduled(scheduler.schedule(days), reason)
        } catch (e: Exception) {
            if (e is kotlinx.coroutines.CancellationException) throw e
            Timber.e(e, "Prayer alarm repair failed")
            runCatching { checkpoints.schedulingFailed("Alarm repair failed: ${e.javaClass.simpleName}") }
                .onFailure { Timber.e(it, "Prayer checkpoint storage unavailable") }
        }
    }
}
