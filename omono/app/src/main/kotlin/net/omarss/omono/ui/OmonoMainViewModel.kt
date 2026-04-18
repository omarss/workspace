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
import kotlinx.coroutines.flow.MutableStateFlow
import net.omarss.omono.feature.speed.ForegroundAppDetector
import net.omarss.omono.feature.speed.InternetGovernor
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
    private val internetGovernor: InternetGovernor,
    private val foregroundApp: ForegroundAppDetector,
    stateHolder: FeatureHostStateHolder,
    tripDao: TripDao,
) : ViewModel() {

    private val speedFeatureId = FeatureId("speed")
    private val spendingFeatureId = FeatureId("spending")

    init {
        // Bind to Shizuku as soon as the VM is created so the settings
        // screen can show readiness without waiting for the user to
        // toggle the feature first.
        internetGovernor.start()
    }

    override fun onCleared() {
        internetGovernor.stop()
    }

    // Settings is split into two sub-flows because Kotlin's combine
    // overload tops out at 5 sources. Base covers speed + spending
    // toggles; internet covers the Shizuku kill-switch pair.
    private val baseSettings = combine(
        speedSettings.unit,
        speedSettings.alertOnOverLimit,
        speedSettings.alertOnPhoneUseWhileDriving,
        spendingSettings.monthlyBudgetSar,
    ) { unit, alertOverLimit, alertPhoneUse, budget ->
        BaseSettings(unit, alertOverLimit, alertPhoneUse, budget)
    }

    // Re-read whenever the user could have changed it — e.g. returning
    // from Settings → Usage access. The screen calls
    // refreshUsageStatsPermission() from a LaunchedEffect on resume.
    private val usageStatsGranted = MutableStateFlow(foregroundApp.hasUsageStatsPermission())

    fun refreshUsageStatsPermission() {
        usageStatsGranted.value = foregroundApp.hasUsageStatsPermission()
    }

    private val internetSettings = combine(
        speedSettings.disableInternetWhileDriving,
        internetGovernor.readiness,
        usageStatsGranted,
    ) { enabled, readiness, usage -> InternetSettings(enabled, readiness, usage) }

    private val mergedSettings = combine(baseSettings, internetSettings) { base, internet ->
        Settings(base, internet)
    }

    val uiState: StateFlow<OmonoMainUiState> = combine(
        mergedSettings,
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

    fun setAlertOnPhoneUseWhileDriving(enabled: Boolean) {
        viewModelScope.launch { speedSettings.setAlertOnPhoneUseWhileDriving(enabled) }
    }

    fun setDisableInternetWhileDriving(enabled: Boolean) {
        viewModelScope.launch { speedSettings.setDisableInternetWhileDriving(enabled) }
    }

    // Triggered from the settings UI when readiness is NoPermission.
    // Shizuku itself manages the dialog UX — we just pass the request.
    fun requestShizukuPermission() {
        internetGovernor.requestPermission(SHIZUKU_PERMISSION_REQUEST_CODE)
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

    private data class BaseSettings(
        val unit: SpeedUnit,
        val alertOnOverLimit: Boolean,
        val alertOnPhoneUseWhileDriving: Boolean,
        val monthlyBudgetSar: Double,
    )

    private data class InternetSettings(
        val disableInternetWhileDriving: Boolean,
        val readiness: InternetGovernor.Readiness,
        val usageStatsGranted: Boolean,
    )

    private data class Settings(
        val base: BaseSettings,
        val internet: InternetSettings,
    )

    private fun buildUiState(
        settings: Settings,
        running: Boolean,
        speedState: FeatureState?,
        spendingState: FeatureState?,
        trips: List<TripEntity>,
    ): OmonoMainUiState {
        val base = settings.base
        val internet = settings.internet
        val speedMetadata = metadataOf(speedState)
        val speedKmh = speedMetadata[FeatureState.META_SPEED_KMH]?.toFloat()
        val limitKmh = speedMetadata[FeatureState.META_SPEED_LIMIT_KMH]?.toFloat()
        val isMoving = speedState is FeatureState.Active

        val heroValue = if (isMoving && speedKmh != null) {
            val mps = speedKmh / 3.6f
            "%.1f".format(base.unit.fromMetersPerSecond(mps))
        } else {
            HERO_PLACEHOLDER
        }
        val limitDisplay = limitKmh?.let { kmh ->
            val mps = kmh / 3.6f
            "%.0f %s".format(base.unit.fromMetersPerSecond(mps), base.unit.label)
        }
        val overLimit = isMoving && speedKmh != null && limitKmh != null && speedKmh > limitKmh

        val status = when {
            !running -> Status.Stopped
            speedState is FeatureState.Active -> Status.Tracking
            speedState is FeatureState.Error -> Status.Error(speedState.message)
            else -> Status.Waiting
        }

        val spending = buildSpendingUi(spendingState, base.monthlyBudgetSar)
        val recentTrips = trips.map(::toTripUi)

        return OmonoMainUiState(
            unit = base.unit,
            running = running,
            heroValue = heroValue,
            heroUnit = base.unit.label,
            status = status,
            limitDisplay = limitDisplay,
            overLimit = overLimit,
            alertOnOverLimit = base.alertOnOverLimit,
            alertOnPhoneUseWhileDriving = base.alertOnPhoneUseWhileDriving,
            usageStatsGranted = internet.usageStatsGranted,
            disableInternetWhileDriving = internet.disableInternetWhileDriving,
            shizukuReadiness = internet.readiness,
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

        // Arbitrary; Shizuku echoes it back on the permission result
        // listener and we don't currently care which request the
        // result came from since omono only makes one.
        const val SHIZUKU_PERMISSION_REQUEST_CODE = 7124
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
    val alertOnPhoneUseWhileDriving: Boolean = false,
    val usageStatsGranted: Boolean = false,
    val disableInternetWhileDriving: Boolean = false,
    val shizukuReadiness: InternetGovernor.Readiness = InternetGovernor.Readiness.Unknown,
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
