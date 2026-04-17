package net.omarss.omono.feature.speed

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

// Hysteresis-based "am I driving?" detector. Fed the filtered speed
// stream from SpeedRepository (one sample per GPS tick) and emits a
// StateFlow<Boolean> the rest of the app can react to — locks the
// phone down, starts the distraction guard, etc.
//
// State machine:
//
//     Idle  --(speed ≥ enter)-->  SpeedingUp  --(sustained enterDur)-->  Driving
//       ^                          |                                        |
//       |                          +--(speed < enter)-- (abandoned)         |
//       |                                                                   v
//       +--(sustained exitDur below exit)--  SlowingDown  <--(speed < exit)--
//                                                |
//                                                +--(speed ≥ exit)--> Driving
//
// Driving and SlowingDown both count as "driving" for consumers — the
// grace period keeps alerts active through a red light instead of
// rearming on every stop. Enter / exit thresholds have a gap (5 km/h
// between them) so a car rolling at 10 km/h in traffic doesn't thrash
// between Driving and Idle.
@Singleton
class DrivingModeDetector @Inject constructor() {

    private val _isDriving = MutableStateFlow(false)
    val isDriving: StateFlow<Boolean> = _isDriving.asStateFlow()

    private var phase: Phase = Phase.Idle
    private var phaseStartedAtMs: Long = 0L

    // Feed one sample per location tick. Pure except for the internal
    // state transition — same inputs produce same output.
    fun onSample(speedMps: Float, nowMs: Long) {
        phase = nextPhase(phase, speedMps, nowMs)
        _isDriving.value = phase == Phase.Driving || phase == Phase.SlowingDown
    }

    // Reset is called when the feature host stops so a restart doesn't
    // inherit a stale "I'm still driving" from the previous run.
    fun reset() {
        phase = Phase.Idle
        phaseStartedAtMs = 0L
        _isDriving.value = false
    }

    private fun nextPhase(current: Phase, speed: Float, nowMs: Long): Phase {
        return when (current) {
            Phase.Idle -> {
                if (speed >= ENTER_MPS) {
                    phaseStartedAtMs = nowMs
                    Phase.SpeedingUp
                } else {
                    Phase.Idle
                }
            }
            Phase.SpeedingUp -> when {
                speed < ENTER_MPS -> Phase.Idle
                nowMs - phaseStartedAtMs >= ENTER_DURATION_MS -> Phase.Driving
                else -> Phase.SpeedingUp
            }
            Phase.Driving -> {
                if (speed < EXIT_MPS) {
                    phaseStartedAtMs = nowMs
                    Phase.SlowingDown
                } else {
                    Phase.Driving
                }
            }
            Phase.SlowingDown -> when {
                speed >= EXIT_MPS -> Phase.Driving
                nowMs - phaseStartedAtMs >= EXIT_DURATION_MS -> Phase.Idle
                else -> Phase.SlowingDown
            }
        }
    }

    private enum class Phase { Idle, SpeedingUp, Driving, SlowingDown }

    internal companion object {
        // Thresholds and durations chosen to match real-world urban
        // driving. Tuned against a handful of Riyadh trips in testing.
        const val ENTER_MPS: Float = 5.5f          // ~20 km/h
        const val EXIT_MPS: Float = 1.4f           // ~5 km/h
        const val ENTER_DURATION_MS: Long = 15_000L // 15 s above 20 km/h = driving
        const val EXIT_DURATION_MS: Long = 120_000L // 2 min below 5 km/h = trip over
    }
}
