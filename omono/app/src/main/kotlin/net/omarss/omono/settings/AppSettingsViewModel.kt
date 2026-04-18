package net.omarss.omono.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

// Activity-scoped VM so the root `OmonoTheme` call in MainActivity can
// read the preference synchronously on first composition. Eagerly
// started so the StateFlow has a real value (not the Auto default) by
// the time the Activity composes its content — avoids a one-frame
// flash of the wrong theme after process restart.
@HiltViewModel
class AppSettingsViewModel @Inject constructor(
    private val appSettings: AppSettingsRepository,
) : ViewModel() {

    val theme: StateFlow<ThemePreference> = appSettings.theme.stateIn(
        scope = viewModelScope,
        started = SharingStarted.Eagerly,
        initialValue = ThemePreference.Auto,
    )

    fun setTheme(preference: ThemePreference) {
        viewModelScope.launch { appSettings.setTheme(preference) }
    }
}
