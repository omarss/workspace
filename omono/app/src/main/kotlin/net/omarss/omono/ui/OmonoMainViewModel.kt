package net.omarss.omono.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.feature.speed.SpeedSettingsRepository
import javax.inject.Inject

@HiltViewModel
class OmonoMainViewModel @Inject constructor(
    private val speedSettings: SpeedSettingsRepository,
) : ViewModel() {

    val unit: StateFlow<SpeedUnit> = speedSettings.unit
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(stopTimeoutMillis = 5_000),
            initialValue = SpeedUnit.KmH,
        )

    fun setUnit(unit: SpeedUnit) {
        viewModelScope.launch { speedSettings.setUnit(unit) }
    }
}
