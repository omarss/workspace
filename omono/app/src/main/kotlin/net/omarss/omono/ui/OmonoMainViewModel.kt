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
    private val spendingFeatureId = FeatureId("spending")

    val uiState: StateFlow<OmonoMainUiState> = combine(
        speedSettings.unit,
        speedSettings.alertOnOverLimit,
        stateHolder.running,
        stateHolder.states,
    ) { unit, alertEnabled, running, states ->
        buildUiState(
            unit = unit,
            alertOnOverLimit = alertEnabled,
            running = running,
            speedState = states[speedFeatureId],
            spendingState = states[spendingFeatureId],
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

    private fun buildUiState(
        unit: SpeedUnit,
        alertOnOverLimit: Boolean,
        running: Boolean,
        speedState: FeatureState?,
        spendingState: FeatureState?,
    ): OmonoMainUiState {
        val speedMetadata = when (speedState) {
            is FeatureState.Active -> speedState.metadata
            is FeatureState.Idle -> speedState.metadata
            else -> emptyMap()
        }
        val speedKmh = speedMetadata[FeatureState.META_SPEED_KMH]?.toFloat()
        val limitKmh = speedMetadata[FeatureState.META_SPEED_LIMIT_KMH]?.toFloat()
        val isMoving = speedState is FeatureState.Active

        val heroValue = if (isMoving && speedKmh != null) {
            val mps = speedKmh / 3.6f
            "%.1f".format(unit.fromMetersPerSecond(mps))
        } else {
            HERO_PLACEHOLDER
        }
        val limitDisplay = limitKmh?.let { kmh ->
            val mps = kmh / 3.6f
            "%.0f %s".format(unit.fromMetersPerSecond(mps), unit.label)
        }
        val overLimit = isMoving && speedKmh != null && limitKmh != null && speedKmh > limitKmh

        val status = when {
            !running -> Status.Stopped
            speedState is FeatureState.Active -> Status.Tracking
            speedState is FeatureState.Error -> Status.Error(speedState.message)
            else -> Status.Waiting
        }

        val spending = buildSpendingUi(spendingState)

        return OmonoMainUiState(
            unit = unit,
            running = running,
            heroValue = heroValue,
            heroUnit = unit.label,
            status = status,
            limitDisplay = limitDisplay,
            overLimit = overLimit,
            alertOnOverLimit = alertOnOverLimit,
            spending = spending,
        )
    }

    private fun buildSpendingUi(state: FeatureState?): SpendingUi {
        if (state is FeatureState.Error) {
            return SpendingUi(available = false, errorMessage = state.message)
        }
        val metadata = when (state) {
            is FeatureState.Active -> state.metadata
            is FeatureState.Idle -> state.metadata
            else -> emptyMap()
        }
        val today = metadata[FeatureState.META_SPENT_TODAY_SAR]
        val month = metadata[FeatureState.META_SPENT_MONTH_SAR]
        if (today == null && month == null) {
            return SpendingUi(available = false)
        }
        return SpendingUi(
            available = true,
            today = today?.let { "%,.0f".format(it) } ?: "—",
            month = month?.let { "%,.0f".format(it) } ?: "—",
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
)

data class SpendingUi(
    val available: Boolean = false,
    val today: String = "—",
    val month: String = "—",
    val errorMessage: String? = null,
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
