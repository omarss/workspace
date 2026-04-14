package net.omarss.omono.core.service

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import javax.inject.Inject
import javax.inject.Singleton

// Shared, process-scoped state between the FeatureHostService and the UI
// layer. The service writes (running / per-feature state), the UI reads.
//
// Using a Hilt @Singleton avoids binding the Activity to the service just
// to peek at current state, and keeps the UI testable — ViewModels can
// inject a fake or spy of this holder.
@Singleton
class FeatureHostStateHolder @Inject constructor() {

    private val _running = MutableStateFlow(false)
    val running: StateFlow<Boolean> = _running.asStateFlow()

    private val _states = MutableStateFlow<Map<FeatureId, FeatureState>>(emptyMap())
    val states: StateFlow<Map<FeatureId, FeatureState>> = _states.asStateFlow()

    internal fun setRunning(value: Boolean) {
        _running.value = value
    }

    internal fun updateState(id: FeatureId, state: FeatureState) {
        _states.update { it + (id to state) }
    }

    internal fun clearStates() {
        _states.value = emptyMap()
    }
}
