package net.omarss.omono.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureHostStateHolder
import net.omarss.omono.core.service.FeatureId
import net.omarss.omono.core.service.FeatureState
import net.omarss.omono.feature.speed.SpeedSettingsRepository
import net.omarss.omono.feature.speed.trips.TripDao
import net.omarss.omono.feature.speed.trips.TripEntity
import net.omarss.omono.feature.spending.SmsExporter
import net.omarss.omono.feature.spending.SpendingSettingsRepository
import timber.log.Timber
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import javax.inject.Inject

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class OmonoMainViewModel @Inject constructor(
    private val speedSettings: SpeedSettingsRepository,
    private val spendingSettings: SpendingSettingsRepository,
    private val smsExporter: SmsExporter,
    stateHolder: FeatureHostStateHolder,
    tripDao: TripDao,
) : ViewModel() {

    private val speedFeatureId = FeatureId("speed")
    private val spendingFeatureId = FeatureId("spending")

    // The root combine is one flow. We collapse the five independent
    // sources into the single UI state the composable observes.
    // Using `combine` (not nested) keeps recomposition cost bounded.
    val uiState: StateFlow<OmonoMainUiState> = combine(
        combine(
            speedSettings.unit,
            speedSettings.alertOnOverLimit,
            speedSettings.alertOnTrafficAhead,
            spendingSettings.monthlyBudgetSar,
        ) { unit, alert, trafficAlert, budget -> Settings(unit, alert, trafficAlert, budget) },
        stateHolder.running,
        stateHolder.states,
        tripDao.observeTop5(),
    ) { settings, running, states, trips ->
        buildUiState(
            settings = settings,
            running = running,
            speedState = states[speedFeatureId],
            spendingState = states[spendingFeatureId],
            trips = trips,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(stopTimeoutMillis = 5_000),
        initialValue = OmonoMainUiState(),
    )

    fun setUnit(unit: SpeedUnit) {
        viewModelScope.launch { speedSettings.setUnit(unit) }
    }

    fun setAlertOnOverLimit(enabled: Boolean) {
        viewModelScope.launch { speedSettings.setAlertOnOverLimit(enabled) }
    }

    fun setAlertOnTrafficAhead(enabled: Boolean) {
        viewModelScope.launch { speedSettings.setAlertOnTrafficAhead(enabled) }
    }

    fun setMonthlyBudget(budgetSar: Double) {
        viewModelScope.launch { spendingSettings.setMonthlyBudgetSar(budgetSar) }
    }

    // One-shot channel for export events. The screen collects it via
    // LaunchedEffect and turns each emission into a FileProvider URI +
    // ACTION_SEND intent — keeping Intent construction out of the VM.
    private val _exportEvents = Channel<ExportEvent>(Channel.BUFFERED)
    val exportEvents: Flow<ExportEvent> = _exportEvents.receiveAsFlow()

    fun onExportSmsRequested() {
        viewModelScope.launch {
            runCatching { smsExporter.export() }
                .onSuccess { result ->
                    _exportEvents.send(ExportEvent.Success(result.file, result.count))
                }
                .onFailure { error ->
                    Timber.w(error, "SMS export failed")
                    _exportEvents.send(ExportEvent.Failure(error.message ?: "Export failed"))
                }
        }
    }

    private data class Settings(
        val unit: SpeedUnit,
        val alertOnOverLimit: Boolean,
        val alertOnTrafficAhead: Boolean,
        val monthlyBudgetSar: Double,
    )

    private fun buildUiState(
        settings: Settings,
        running: Boolean,
        speedState: FeatureState?,
        spendingState: FeatureState?,
        trips: List<TripEntity>,
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
            alertOnTrafficAhead = settings.alertOnTrafficAhead,
            spending = spending,
            recentTrips = recentTrips,
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
    val alertOnTrafficAhead: Boolean = false,
    val spending: SpendingUi = SpendingUi(),
    val recentTrips: List<TripUi> = emptyList(),
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
