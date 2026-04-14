package net.omarss.omono.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
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
import javax.inject.Inject

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class OmonoMainViewModel @Inject constructor(
    private val speedSettings: SpeedSettingsRepository,
    stateHolder: FeatureHostStateHolder,
) : ViewModel() {

    private val speedFeatureId = FeatureId("speed")

    val uiState: StateFlow<OmonoMainUiState> = combine(
        speedSettings.unit,
        stateHolder.running,
        stateHolder.states,
    ) { unit, running, states ->
        buildUiState(unit, running, states[speedFeatureId])
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(stopTimeoutMillis = 5_000),
        initialValue = OmonoMainUiState(),
    )

    fun setUnit(unit: SpeedUnit) {
        viewModelScope.launch { speedSettings.setUnit(unit) }
    }

    private fun buildUiState(
        unit: SpeedUnit,
        running: Boolean,
        speedState: FeatureState?,
    ): OmonoMainUiState {
        val (value, label) = parseSummary(speedState?.summary, unit)
        val status = when {
            !running -> Status.Stopped
            speedState is FeatureState.Active -> Status.Tracking
            speedState is FeatureState.Error -> Status.Error(speedState.message)
            else -> Status.Waiting
        }
        return OmonoMainUiState(
            unit = unit,
            running = running,
            heroValue = value,
            heroUnit = label ?: unit.label,
            status = status,
        )
    }

    // Both Active and Idle summaries follow "<value> <unit>" by construction
    // (see formatSpeedState in :feature:speed). Split on the last space so we
    // can render the value big and the unit label small.
    private fun parseSummary(summary: String?, fallbackUnit: SpeedUnit): Pair<String, String?> {
        if (summary.isNullOrBlank()) return HERO_PLACEHOLDER to fallbackUnit.label
        val idx = summary.lastIndexOf(' ')
        if (idx <= 0) return summary to null
        return summary.substring(0, idx) to summary.substring(idx + 1)
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
)

sealed interface Status {
    val label: String

    data object Stopped : Status { override val label: String = "Stopped" }
    data object Waiting : Status { override val label: String = "Waiting for GPS fix" }
    data object Tracking : Status { override val label: String = "Tracking" }
    data class Error(val message: String) : Status {
        override val label: String get() = "Error: $message"
    }
}
