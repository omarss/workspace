package net.omarss.omono.ui.prayer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.omarss.omono.feature.prayer.AthanPlayer
import net.omarss.omono.feature.prayer.PrayerDayTimes
import net.omarss.omono.feature.prayer.PrayerKind
import net.omarss.omono.feature.prayer.PrayerLocationCache
import net.omarss.omono.feature.prayer.PrayerScheduler
import net.omarss.omono.feature.prayer.PrayerSettingsRepository
import net.omarss.omono.feature.prayer.PrayerTimesCalculator
import net.omarss.omono.location.AppLocationStream
import timber.log.Timber
import java.io.File
import java.time.LocalDate
import java.time.ZoneId
import javax.inject.Inject

// Owns the prayer-times screen. Collects the shared AppLocationStream
// so every new GPS fix updates the day's schedule + reschedules the
// alarms. Falls back to the persisted last-known location on cold
// start so a user opening the tab offline still sees approximate
// times for their usual location.
@HiltViewModel
class PrayerViewModel @Inject constructor(
    private val locationStream: AppLocationStream,
    private val locationCache: PrayerLocationCache,
    private val settings: PrayerSettingsRepository,
    private val scheduler: PrayerScheduler,
    private val athanPlayer: AthanPlayer,
) : ViewModel() {

    private val _state = MutableStateFlow(PrayerUiState())
    val state: StateFlow<PrayerUiState> = _state.asStateFlow()

    private var recomputeJob: Job? = null

    init {
        viewModelScope.launch {
            // Seed from the cache so the screen isn't blank while
            // waiting for the first fix. If no fix has ever been
            // saved, the tab shows a "Waiting for GPS" empty state.
            val seeded = locationCache.last.first()
            if (seeded != null) {
                recompute(seeded.latitude, seeded.longitude)
            }
        }
        // Stream fresh GPS fixes — each update saves to the cache and
        // recomputes + reschedules. Fires only when the user's moved
        // far enough to matter (AppLocationStream's own filter is
        // ~5 m / 3 s, which is far tighter than a prayer-time delta
        // needs — fine to react to each emission).
        viewModelScope.launch {
            if (!locationStream.hasPermission()) {
                _state.update { it.copy(permissionDenied = true) }
                return@launch
            }
            runCatching {
                locationStream.updates().collect { fix ->
                    locationCache.save(fix.latitude, fix.longitude)
                    recompute(fix.latitude, fix.longitude)
                }
            }.onFailure {
                Timber.w(it, "prayer location stream failed")
                _state.update { it.copy(permissionDenied = true) }
            }
        }
        // Tick the "next prayer in X minutes" label every 30 s. It
        // doesn't need to be a full second resolution — the card
        // just has to feel alive.
        viewModelScope.launch {
            while (true) {
                delay(30_000L)
                _state.update { it.copy(now = System.currentTimeMillis()) }
            }
        }
    }

    // Manual refresh button — re-requests a GPS fix by kicking the
    // stream to emit again. The subscription above is still running
    // too, so this is mostly a "nudge" for UX.
    fun refresh() {
        val last = _state.value.lastFix ?: return
        recompute(last.first, last.second)
    }

    fun playAthanPreview() {
        athanPlayer.playRandom()
    }

    fun stopAthanPreview() {
        athanPlayer.stop()
    }

    fun athansDirectory(): File = athanPlayer.athansDirectory()

    private fun recompute(lat: Double, lon: Double) {
        recomputeJob?.cancel()
        recomputeJob = viewModelScope.launch {
            val snap = settings.snapshot.first()
            val today = LocalDate.now(ZoneId.systemDefault())
            val day = runCatching {
                PrayerTimesCalculator.computeDay(lat, lon, today, snap)
            }.onFailure { Timber.w(it, "prayer compute failed") }
                .getOrNull()
            if (day != null) {
                scheduler.schedule(day)
                // Also queue tomorrow's Fajr so users who only open
                // the app once a day still get the next morning's
                // alarm without another launch.
                val tomorrow = runCatching {
                    PrayerTimesCalculator.computeDay(lat, lon, today.plusDays(1), snap)
                }.getOrNull()
                if (tomorrow != null) scheduler.schedule(tomorrow)

                _state.update {
                    it.copy(
                        today = day,
                        lastFix = lat to lon,
                        permissionDenied = false,
                        now = System.currentTimeMillis(),
                    )
                }
            }
        }
    }
}

data class PrayerUiState(
    val today: PrayerDayTimes? = null,
    val lastFix: Pair<Double, Double>? = null,
    val permissionDenied: Boolean = false,
    val now: Long = System.currentTimeMillis(),
) {
    val nextPrayer: net.omarss.omono.feature.prayer.PrayerTime?
        get() = today?.nextAfter(now)

    val currentPrayer: net.omarss.omono.feature.prayer.PrayerTime?
        get() = today?.currentOrNull(now)
}
