package net.omarss.omono.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.diagnostics.DiagnosticsLogger
import net.omarss.omono.feature.speed.ForegroundAppDetector
import net.omarss.omono.feature.speed.InternetGovernor
import net.omarss.omono.feature.speed.SpeedSettingsRepository
import net.omarss.omono.feature.spending.SmsExporter
import net.omarss.omono.feature.spending.SpendingSettingsRepository
import net.omarss.omono.ui.ExportEvent
import timber.log.Timber
import java.io.File
import javax.inject.Inject

// Concentrates every user-visible preference + setup action into a
// single VM for the new Settings destination. Repositories are all
// Hilt singletons, so this VM reads + writes the same state
// OmonoMainViewModel observes — no duplication of truth.
//
// Shizuku's listener lifecycle also lives here: the Settings screen
// is the only surface that renders readiness, so start/stop the
// governor with the VM itself.
@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val speedSettings: SpeedSettingsRepository,
    private val spendingSettings: SpendingSettingsRepository,
    private val smsExporter: SmsExporter,
    private val internetGovernor: InternetGovernor,
    private val foregroundApp: ForegroundAppDetector,
    private val diagnosticsLogger: DiagnosticsLogger,
) : ViewModel() {

    // Shizuku governor lifecycle is managed at the Application level —
    // the SettingsViewModel just reads the readiness flow the
    // singleton already exposes.

    // Re-read on every ON_RESUME so returning from Settings → Usage
    // access immediately reflects the new state.
    private val usageStatsGranted = MutableStateFlow(foregroundApp.hasUsageStatsPermission())

    fun refreshUsageStatsPermission() {
        usageStatsGranted.value = foregroundApp.hasUsageStatsPermission()
    }

    // Two combines wide and stacked because Kotlin's combine overload
    // tops out at 5 flows.
    private val baseFlow: Flow<BaseSettings> = combine(
        speedSettings.unit,
        speedSettings.alertOnOverLimit,
        speedSettings.alertOnPhoneUseWhileDriving,
        speedSettings.disableInternetWhileDriving,
        spendingSettings.monthlyBudgetSar,
    ) { unit, alertOverLimit, alertPhoneUse, disableInternet, budget ->
        BaseSettings(unit, alertOverLimit, alertPhoneUse, disableInternet, budget)
    }

    private val accessFlow: Flow<AccessState> = combine(
        usageStatsGranted,
        internetGovernor.readiness,
    ) { usageStats, readiness ->
        AccessState(usageStats, readiness)
    }

    val uiState: StateFlow<SettingsUiState> = combine(baseFlow, accessFlow) { base, access ->
        SettingsUiState(
            unit = base.unit,
            alertOnOverLimit = base.alertOnOverLimit,
            alertOnPhoneUseWhileDriving = base.alertOnPhoneUseWhileDriving,
            usageStatsGranted = access.usageStatsGranted,
            disableInternetWhileDriving = base.disableInternetWhileDriving,
            shizukuReadiness = access.shizukuReadiness,
            monthlyBudgetSar = base.monthlyBudgetSar,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(stopTimeoutMillis = 5_000),
        initialValue = SettingsUiState(),
    )

    // One-shot export events surfaced to the UI the same way
    // OmonoMainViewModel does — the composable turns each into a
    // FileProvider ACTION_SEND intent.
    private val _exportEvents = Channel<ExportEvent>(Channel.BUFFERED)
    val exportEvents: Flow<ExportEvent> = _exportEvents.receiveAsFlow()

    // Separate channel for diagnostics so the UI can give it its own
    // subject line / chooser label without branching on a generic event.
    private val _diagnosticsEvents = Channel<DiagnosticsShareEvent>(Channel.BUFFERED)
    val diagnosticsEvents: Flow<DiagnosticsShareEvent> = _diagnosticsEvents.receiveAsFlow()

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

    fun setMonthlyBudget(budgetSar: Double) {
        viewModelScope.launch { spendingSettings.setMonthlyBudgetSar(budgetSar) }
    }

    fun requestShizukuPermission() {
        internetGovernor.requestPermission(SHIZUKU_PERMISSION_REQUEST_CODE)
    }

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

    // Concatenates the rolling Timber log file into the app cache and
    // hands it off to the UI for FileProvider sharing.
    fun onShareDiagnosticsRequested() {
        viewModelScope.launch {
            runCatching { diagnosticsLogger.buildSharePayload() }
                .onSuccess { file -> _diagnosticsEvents.send(DiagnosticsShareEvent.Success(file)) }
                .onFailure { error ->
                    Timber.w(error, "Diagnostics share failed")
                    _diagnosticsEvents.send(
                        DiagnosticsShareEvent.Failure(error.message ?: "Could not prepare log"),
                    )
                }
        }
    }

    private data class BaseSettings(
        val unit: SpeedUnit,
        val alertOnOverLimit: Boolean,
        val alertOnPhoneUseWhileDriving: Boolean,
        val disableInternetWhileDriving: Boolean,
        val monthlyBudgetSar: Double,
    )

    private data class AccessState(
        val usageStatsGranted: Boolean,
        val shizukuReadiness: InternetGovernor.Readiness,
    )

    private companion object {
        const val SHIZUKU_PERMISSION_REQUEST_CODE = 7124
    }
}

data class SettingsUiState(
    val unit: SpeedUnit = SpeedUnit.KmH,
    val alertOnOverLimit: Boolean = true,
    val alertOnPhoneUseWhileDriving: Boolean = false,
    val usageStatsGranted: Boolean = false,
    val disableInternetWhileDriving: Boolean = false,
    val shizukuReadiness: InternetGovernor.Readiness = InternetGovernor.Readiness.Unknown,
    val monthlyBudgetSar: Double = 0.0,
)

sealed interface DiagnosticsShareEvent {
    data class Success(val file: File) : DiagnosticsShareEvent
    data class Failure(val message: String) : DiagnosticsShareEvent
}
