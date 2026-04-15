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
        val metadata = when (speedState) {
            is FeatureState.Active -> speedState.metadata
            is FeatureState.Idle -> speedState.metadata
            else -> emptyMap()
        }
        val speedKmh = metadata[FeatureState.META_SPEED_KMH]?.toFloat()
        val limitKmh = metadata[FeatureState.META_SPEED_LIMIT_KMH]?.toFloat()
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
        return OmonoMainUiState(
            unit = unit,
            running = running,
            heroValue = heroValue,
            heroUnit = unit.label,
            status = status,
            limitDisplay = limitDisplay,
            overLimit = overLimit,
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
