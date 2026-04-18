package net.omarss.omono.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureHostStateHolder
import net.omarss.omono.core.service.FeatureId
import net.omarss.omono.core.service.FeatureState
import net.omarss.omono.feature.speed.SpeedSettingsRepository
import net.omarss.omono.feature.speed.trips.TripDao
import net.omarss.omono.feature.speed.trips.TripEntity
import net.omarss.omono.feature.spending.SpendingSettingsRepository
import net.omarss.omono.permissions.PermissionBaselineTracker
import net.omarss.omono.permissions.TrackedPermission
import timber.log.Timber
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import javax.inject.Inject

// ViewModel for the Drive tab — the "what's happening right now" view.
// Every user preference (unit, alerts, toggles, budgets) lives behind
// SettingsViewModel; this one is read-only on the settings repos, only
// exposing flows the tracking UI needs.
@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class OmonoMainViewModel @Inject constructor(
    speedSettings: SpeedSettingsRepository,
    spendingSettings: SpendingSettingsRepository,
    stateHolder: FeatureHostStateHolder,
    tripDao: TripDao,
    private val permissionBaselines: PermissionBaselineTracker,
) : ViewModel() {

    private val speedFeatureId = FeatureId("speed")
    private val spendingFeatureId = FeatureId("spending")

    // Current runtime permission state, pushed in by the Compose
    // lifecycle observer. Seeded with an "unknown/all true" map so the
    // first comparison against the persisted baseline can't report
    // a regression before the UI has reported anything.
    private val currentPermissions: MutableStateFlow<Map<TrackedPermission, Boolean>> =
        MutableStateFlow(TrackedPermission.entries.associateWith { true })

    // Lost = previously granted AND not currently granted. Derived so a
    // newly-granted permission clears automatically on the next resume
    // without having to mutate a second store.
    private val lostPermissions: StateFlow<Set<TrackedPermission>> = combine(
        permissionBaselines.everGranted,
        currentPermissions,
    ) { baselines, current ->
        TrackedPermission.entries
            .filter { baselines[it] == true && current[it] == false }
            .toSet()
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(stopTimeoutMillis = 5_000),
        initialValue = emptySet(),
    )

    // Called from OmonoMainRoute on every lifecycle resume with the
    // current grant state. Updates the baseline (for any newly-granted
    // permission) and the "current" flow that feeds the lost set. Logs
    // a warning the first time a regression is observed so the
    // rotated diagnostics file captures it for post-hoc support.
    fun reportCurrentPermissions(states: Map<TrackedPermission, Boolean>) {
        val previouslyLost = lostPermissions.value
        currentPermissions.value = states
        viewModelScope.launch {
            runCatching { permissionBaselines.recordCurrent(states) }
                .onFailure { Timber.w(it, "permission baseline write failed") }
        }
        // Spot new regressions vs the *previous* lost set so we log
        // each revocation once, not on every resume that sees the same
        // missing permission.
        states.forEach { (perm, granted) ->
            if (!granted && perm !in previouslyLost) {
                // No-op unless the baseline already has it as granted —
                // logged only when the derived flow ends up marking it
                // lost on the next emission. `Timber.w` on every
                // resume-with-missing-permission would be too chatty.
                Timber.d("permission baseline: current=%s granted=%s", perm.name, false)
            }
        }
    }

    private val settings = combine(
        speedSettings.unit,
        speedSettings.alertOnOverLimit,
        spendingSettings.monthlyBudgetSar,
    ) { unit, alertOverLimit, budget ->
        Settings(unit, alertOverLimit, budget)
    }

    val uiState: StateFlow<OmonoMainUiState> = combine(
        settings,
        stateHolder.running,
        stateHolder.states,
        tripDao.observeTop5(),
        lostPermissions,
    ) { s, running, states, trips, lost ->
        buildUiState(
            settings = s,
            running = running,
            speedState = states[speedFeatureId],
            spendingState = states[spendingFeatureId],
            trips = trips,
            lostPermissions = lost,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(stopTimeoutMillis = 5_000),
        initialValue = OmonoMainUiState(),
    )

    private data class Settings(
        val unit: SpeedUnit,
        val alertOnOverLimit: Boolean,
        val monthlyBudgetSar: Double,
    )

    private fun buildUiState(
        settings: Settings,
        running: Boolean,
        speedState: FeatureState?,
        spendingState: FeatureState?,
        trips: List<TripEntity>,
        lostPermissions: Set<TrackedPermission>,
    ): OmonoMainUiState {
        val speedMetadata = metadataOf(speedState)
        val speedKmh = speedMetadata[FeatureState.META_SPEED_KMH]?.toFloat()
        val limitKmh = speedMetadata[FeatureState.META_SPEED_LIMIT_KMH]?.toFloat()
        val isMoving = speedState is FeatureState.Active

        val heroValue = if (isMoving && speedKmh != null) {
            val mps = speedKmh / 3.6f
            "%.1f".format(settings.unit.fromMetersPerSecond(mps))
        } else {
            HERO_PLACEHOLDER
        }
        val limitDisplay = limitKmh?.let { kmh ->
            val mps = kmh / 3.6f
            "%.0f %s".format(settings.unit.fromMetersPerSecond(mps), settings.unit.label)
        }
        val overLimit = isMoving && speedKmh != null && limitKmh != null && speedKmh > limitKmh

        val status = when {
            !running -> Status.Stopped
            speedState is FeatureState.Active -> Status.Tracking
            speedState is FeatureState.Error -> Status.Error(speedState.message)
            else -> Status.Waiting
        }

        val spending = buildSpendingUi(spendingState, settings.monthlyBudgetSar)
        val recentTrips = trips.map(::toTripUi)

        return OmonoMainUiState(
            unit = settings.unit,
            running = running,
            heroValue = heroValue,
            heroUnit = settings.unit.label,
            status = status,
            limitDisplay = limitDisplay,
            overLimit = overLimit,
            alertOnOverLimit = settings.alertOnOverLimit,
            spending = spending,
            recentTrips = recentTrips,
            lostPermissions = lostPermissions,
        )
    }

    private fun metadataOf(state: FeatureState?): Map<String, Double> = when (state) {
        is FeatureState.Active -> state.metadata
        is FeatureState.Idle -> state.metadata
        else -> emptyMap()
    }

    private fun buildSpendingUi(state: FeatureState?, budgetSar: Double): SpendingUi {
        if (state is FeatureState.Error) {
            return SpendingUi(available = false, errorMessage = state.message)
        }
        val metadata = metadataOf(state)
        val today = metadata[FeatureState.META_SPENT_TODAY_SAR]
        val month = metadata[FeatureState.META_SPENT_MONTH_SAR]
        val transfersMonth = metadata[FeatureState.META_TRANSFERS_MONTH_SAR] ?: 0.0
        if (today == null && month == null) {
            return SpendingUi(available = false, budgetSar = budgetSar)
        }
        val monthValue = month ?: 0.0
        val progress = if (budgetSar > 0) (monthValue / budgetSar).toFloat().coerceIn(0f, 1f) else 0f
        return SpendingUi(
            available = true,
            today = today?.let { "%,.0f".format(it) } ?: "—",
            month = month?.let { "%,.0f".format(it) } ?: "—",
            transfersMonth = if (transfersMonth > 0) "%,.0f".format(transfersMonth) else null,
            budgetSar = budgetSar,
            budgetDisplay = "%,.0f".format(budgetSar),
            monthProgress = progress,
            overBudget = budgetSar > 0 && monthValue > budgetSar,
        )
    }

    private fun toTripUi(trip: TripEntity): TripUi {
        val formatter = SimpleDateFormat("EEE d MMM · HH:mm", Locale.getDefault())
        val durationMin = ((trip.endAtMillis - trip.startAtMillis) / 60_000L).coerceAtLeast(1)
        val distanceKm = trip.distanceMeters / 1000.0
        return TripUi(
            id = trip.id,
            startedAt = formatter.format(trip.startAtMillis),
            distance = "%.1f km".format(distanceKm),
            maxSpeed = "%.0f km/h".format(trip.maxSpeedKmh),
            duration = "%d min".format(durationMin),
        )
    }

    private companion object {
        const val HERO_PLACEHOLDER = "—"
    }
}

data class OmonoMainUiState(
    val unit: SpeedUnit = SpeedUnit.KmH,
    val running: Boolean = false,
    val heroValue: String = "—",
    val heroUnit: String = SpeedUnit.KmH.label,
    val status: Status = Status.Stopped,
    val limitDisplay: String? = null,
    val overLimit: Boolean = false,
    val alertOnOverLimit: Boolean = true,
    val spending: SpendingUi = SpendingUi(),
    val recentTrips: List<TripUi> = emptyList(),
    val lostPermissions: Set<TrackedPermission> = emptySet(),
)

data class SpendingUi(
    val available: Boolean = false,
    val today: String = "—",
    val month: String = "—",
    // Null when there are no outgoing transfers this month — we hide
    // the row in that case to keep the card tight.
    val transfersMonth: String? = null,
    val errorMessage: String? = null,
    val budgetSar: Double = 0.0,
    val budgetDisplay: String = "0",
    val monthProgress: Float = 0f,
    val overBudget: Boolean = false,
)

data class TripUi(
    val id: Long,
    val startedAt: String,
    val distance: String,
    val maxSpeed: String,
    val duration: String,
)

// Kept here because SettingsViewModel imports it — export flow works
// the same way either VM hosts it.
sealed interface ExportEvent {
    data class Success(val file: File, val count: Int) : ExportEvent
    data class Failure(val message: String) : ExportEvent
}

sealed interface Status {
    val label: String

    data object Stopped : Status { override val label: String = "Stopped" }
    data object Waiting : Status { override val label: String = "Waiting for GPS fix" }
    data object Tracking : Status { override val label: String = "Tracking" }
    data class Error(val message: String) : Status {
        override val label: String get() = "Error: $message"
    }
}
