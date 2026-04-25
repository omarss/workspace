package net.omarss.omono.ui.prayer

import android.content.Context
import android.content.Intent
import android.location.Geocoder
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.getSystemService
import androidx.core.net.toUri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import net.omarss.omono.feature.prayer.AthanItem
import net.omarss.omono.feature.prayer.AthanPlayer
import net.omarss.omono.feature.prayer.AthanSelection
import net.omarss.omono.feature.prayer.PrayerCalculationMethod
import net.omarss.omono.feature.prayer.PrayerDayTimes
import net.omarss.omono.feature.prayer.PrayerKeepAliveService
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
import java.util.Locale
import javax.inject.Inject

// Owns the prayer-times screen. Collects the shared AppLocationStream
// so every new GPS fix updates the day's schedule + reschedules the
// alarms. Falls back to the persisted last-known location on cold
// start so a user opening the tab offline still sees approximate
// times for their usual location.
@HiltViewModel
class PrayerViewModel @Inject constructor(
    @param:ApplicationContext private val context: Context,
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
        // Mirror the persisted athan selection + current method badge
        // into UI state so the Prayer tab renders without another
        // suspend per render.
        viewModelScope.launch {
            settings.snapshot.collect { snap ->
                _state.update {
                    it.copy(
                        athanSelection = snap.athanSelection,
                        method = snap.method,
                    )
                }
            }
        }
        // Reliability-mode mirror: when the user flips it on we kick
        // the foreground service; when off, we stop it.
        viewModelScope.launch {
            settings.reliabilityMode.collect { enabled ->
                _state.update { it.copy(reliabilityMode = enabled) }
                if (enabled) {
                    PrayerKeepAliveService.start(context)
                } else {
                    PrayerKeepAliveService.stop(context)
                }
            }
        }
        viewModelScope.launch {
            settings.requireChallengeToStop.collect { enabled ->
                _state.update { it.copy(requireChallengeToStop = enabled) }
            }
        }
        // Re-check battery-optimisation status whenever the user
        // returns to the tab — they might have just granted it via
        // the system Settings deep-link below.
        refreshBatteryOptStatus()
        // Poll the athans directory so the file list + pickability
        // update after an import / delete without a rotation tap.
        refreshAthansList()
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
        athanPlayer.play(_state.value.athanSelection)
    }

    fun stopAthanPreview() {
        athanPlayer.stop()
    }

    fun athansDirectory(): File = athanPlayer.athansDirectory()

    // Pick a specific file by name, or Random to rotate. Persisted
    // immediately so a reboot / app kill keeps the choice.
    fun selectAthan(selection: AthanSelection) {
        viewModelScope.launch { settings.setAthanSelection(selection) }
    }

    // Called after the SAF document-picker returns a content:// uri.
    // AthanPlayer.importFromUri copies the bytes into the app's own
    // athans directory so the Fajr alarm receiver can read them even
    // after the SAF permission has been revoked.
    fun importAthanFromUri(uri: Uri) {
        viewModelScope.launch {
            val copied = withContext(Dispatchers.IO) { athanPlayer.importFromUri(uri) }
            if (copied != null) {
                Timber.i("imported athan %s", copied.name)
                refreshAthansList()
            }
        }
    }

    // Only Local items are deletable; Bundled items live in the APK
    // and can't be removed at runtime. The UI only shows a delete
    // button on Local rows, so this silently no-ops for Bundled.
    fun setReliabilityMode(enabled: Boolean) {
        viewModelScope.launch { settings.setReliabilityMode(enabled) }
    }

    fun setRequireChallengeToStop(enabled: Boolean) {
        viewModelScope.launch { settings.setRequireChallengeToStop(enabled) }
    }

    // True if the OS is currently exempting omono from battery
    // optimisations — without that exemption Doze can deliver alarms
    // late on most OEMs even with setAlarmClock.
    fun refreshBatteryOptStatus() {
        val pm = context.getSystemService<PowerManager>() ?: return
        val ignoring = runCatching {
            pm.isIgnoringBatteryOptimizations(context.packageName)
        }.getOrDefault(false)
        _state.update { it.copy(ignoringBatteryOptimisations = ignoring) }
    }

    // Deep-link the user to the system-Settings page where they can
    // grant the exemption. Falls back to the generic battery-saver
    // settings page on devices that refuse the targeted intent.
    fun launchBatteryOptSettings() {
        val targeted = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
            data = "package:${context.packageName}".toUri()
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val started = runCatching { context.startActivity(targeted) }.isSuccess
        if (!started) {
            val generic = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            runCatching { context.startActivity(generic) }
                .onFailure { Timber.w(it, "battery-opt settings deep-link failed") }
        }
    }

    fun deleteAthan(item: AthanItem) {
        if (item !is AthanItem.Local) return
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) { athanPlayer.deleteAthan(item.file) }
            if (ok) {
                // If the deleted item was pinned, drop the pin so
                // the player auto-rolls back to Random on the next
                // Fajr instead of silently falling through.
                val sel = _state.value.athanSelection
                if (sel is AthanSelection.Specific && sel.fileName == item.identifier) {
                    settings.setAthanSelection(AthanSelection.Random)
                }
                refreshAthansList()
            }
        }
    }

    private fun refreshAthansList() {
        viewModelScope.launch(Dispatchers.IO) {
            val items = athanPlayer.availableAthans()
            _state.update { it.copy(availableAthans = items) }
        }
    }

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
                // Reverse-geocode on a background dispatcher — the
                // Geocoder call blocks for up to a few seconds the
                // first time it's used, and we don't want that to
                // delay the prayer-list render.
                resolveLocationLabel(lat, lon)
            }
        }
    }

    private fun resolveLocationLabel(lat: Double, lon: Double) {
        viewModelScope.launch(Dispatchers.IO) {
            val label = runCatching {
                val geocoder = Geocoder(context, Locale.getDefault())
                @Suppress("DEPRECATION")
                val results = geocoder.getFromLocation(lat, lon, 1)
                val first = results?.firstOrNull()
                buildLocationLabel(first)
            }.getOrNull()
            if (label != null) {
                _state.update { it.copy(locationLabel = label) }
            }
        }
    }

    private fun buildLocationLabel(address: android.location.Address?): String? {
        if (address == null) return null
        val locality = address.locality ?: address.subAdminArea
        val country = address.countryName
        return listOfNotNull(locality, country).joinToString(", ")
            .takeIf { it.isNotBlank() }
    }
}

data class PrayerUiState(
    val today: PrayerDayTimes? = null,
    val lastFix: Pair<Double, Double>? = null,
    val locationLabel: String? = null,
    val method: PrayerCalculationMethod = PrayerCalculationMethod.UmmAlQura,
    val athanSelection: AthanSelection = AthanSelection.Random,
    val availableAthans: List<AthanItem> = emptyList(),
    val reliabilityMode: Boolean = false,
    val requireChallengeToStop: Boolean = false,
    val ignoringBatteryOptimisations: Boolean = true,
    val permissionDenied: Boolean = false,
    val now: Long = System.currentTimeMillis(),
) {
    val nextPrayer: net.omarss.omono.feature.prayer.PrayerTime?
        get() = today?.nextAfter(now)

    val currentPrayer: net.omarss.omono.feature.prayer.PrayerTime?
        get() = today?.currentOrNull(now)
}
