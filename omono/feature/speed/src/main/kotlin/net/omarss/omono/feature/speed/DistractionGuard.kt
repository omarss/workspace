package net.omarss.omono.feature.speed

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Beeps when the user is actively using the phone for something other
// than navigation while driving.
//
// Armed only when ALL of these align — any one flipping stops the
// beep loop within one combine tick:
//
//   1. Feature is enabled (the setting toggle).
//   2. The vehicle-mode gate is held high — tighter than a raw speed
//      threshold so walking / jogging / casual cycling don't trip it.
//      Enters vehicle mode once speed has been above VEHICLE_ENTER_MPS
//      (~25 km/h) for VEHICLE_ENTER_DURATION_MS sustained, holds
//      through red lights via a quick exit grace, and drops back out
//      when the user's been below VEHICLE_EXIT_MPS for
//      VEHICLE_EXIT_DURATION_MS. Mirrors DrivingModeDetector's
//      hysteresis but with a fast exit (seconds, not minutes) because
//      an alert that lingers after you park is worse than one that
//      rearms after the next light.
//   3. Screen is on.
//   4. None of the silence conditions hold:
//        - Proximity sensor covered (phone face-down / in pocket).
//        - Device is on a call (AudioManager mode in IN_CALL / IN_COMMUNICATION).
//
// NOTE: We used to also gate on an accelerometer-variance "phone in
// hand" signal, but in practice it gave too many false negatives —
// a dashboard-mounted phone being tap-scrolled with a thumb barely
// moves the whole device, so variance stayed below the stillness
// threshold and the alert silently never fired. The driver-safe
// conservative default is to alert whenever the screen is on while
// moving and let the proximity / nav-app / call gates handle the
// legitimate "phone isn't being used" cases.
//
// KNOWN LIMITATION: GPS speed alone can't tell a car driver apart
// from a bus / metro / taxi passenger at the same speed. To filter
// those out we'd need a second signal — Bluetooth-to-your-own-car
// being the cleanest. Not built yet; left for a follow-up setting.
//
// After armed=true the loop waits out GRACE_MS before the first beep so
// a notification that briefly wakes the screen or a misfire doesn't
// trigger. While armed, every POLL_INTERVAL_MS it checks the current
// foreground app and pauses beeping when it's a recognised navigation
// app — "eyes on Google Maps" is the whole point of letting you drive
// with the phone mounted in the first place.
//
// UsageStats permission is optional; without it the detector reports
// null foreground and the guard treats that conservatively (beep). The
// settings UI surfaces the permission state so the user can grant it.
@Singleton
class DistractionGuard @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val settings: SpeedSettingsRepository,
    private val alertPlayer: SpeedAlertPlayer,
    private val speedRepository: SpeedRepository,
    private val foregroundApp: ForegroundAppDetector,
) {

    private var beepLoopJob: Job? = null

    fun attach(scope: CoroutineScope) {
        scope.launch {
            // Group the "something silences us" signals into a single
            // boolean so the top-level combine stays under Kotlin's 5-
            // flow overload. Any one of these being true = silenced.
            //
            // The phone-in-hand signal is back, but with a very low
            // variance threshold (see SilenceSignals.phoneInHandFlow)
            // and a hold window — we only silence on *prolonged*
            // stillness (8 s under 0.05 m²/s⁴). A dashboard-mounted
            // phone in a moving car picks up enough road vibration to
            // stay "active", but a phone laid flat on a seat with
            // no-one using it drops to "still" and the beep stops.
            val silencedFlow: Flow<Boolean> = combine(
                context.proximityCoveredFlow(),
                context.inCallFlow(),
                context.phoneInHandFlow(),
            ) { proxCovered, inCall, active ->
                proxCovered || inCall || !active
            }

            combine(
                vehicleModeFlow(),
                context.screenOnFlow(),
                settings.alertOnPhoneUseWhileDriving,
                silencedFlow,
            ) { inVehicle, screenOn, enabled, silenced ->
                enabled && inVehicle && screenOn && !silenced
            }
                .distinctUntilChanged()
                .collect { armed ->
                    if (armed) {
                        beepLoopJob?.cancel()
                        beepLoopJob = scope.launch { runBeepLoop() }
                    } else {
                        beepLoopJob?.cancel()
                        beepLoopJob = null
                        alertPlayer.stopBeeping()
                    }
                }
        }
    }

    // Emits `true` while the user is plausibly in a moving vehicle,
    // `false` otherwise. Two-phase hysteresis:
    //
    //   * Enter: speed >= VEHICLE_ENTER_MPS continuously for
    //     VEHICLE_ENTER_DURATION_MS. Both a high floor (~25 km/h) and
    //     a sustain window are needed — a sprint or a bike downhill
    //     can briefly touch 25 km/h but won't hold it for 15 s.
    //   * Exit: speed < VEHICLE_EXIT_MPS continuously for
    //     VEHICLE_EXIT_DURATION_MS. Short enough that the alert
    //     stops quickly after you park or step off a bus, long
    //     enough that a red light doesn't rearm the enter phase.
    //
    // Driven by a 500 ms ticker combined with the speed StateFlow so
    // transitions keep firing even when the GPS callback falls
    // silent at zero speed.
    private fun vehicleModeFlow(): Flow<Boolean> {
        val ticker: Flow<Unit> = flow {
            while (true) {
                emit(Unit)
                delay(TICK_MS)
            }
        }
        var inVehicle = false
        var enterStartedAtMs: Long? = null
        var exitStartedAtMs: Long? = null
        return combine(speedRepository.currentSpeedMps, ticker) { s, _ ->
            val now = System.currentTimeMillis()
            if (!inVehicle) {
                if (s >= VEHICLE_ENTER_MPS) {
                    val start = enterStartedAtMs ?: now.also { enterStartedAtMs = it }
                    if (now - start >= VEHICLE_ENTER_DURATION_MS) {
                        inVehicle = true
                        exitStartedAtMs = null
                    }
                } else {
                    // Any sample below the enter floor restarts the
                    // sustain clock — the 15 s window has to be a
                    // *continuous* run of above-threshold samples.
                    enterStartedAtMs = null
                }
            } else {
                if (s < VEHICLE_EXIT_MPS) {
                    val start = exitStartedAtMs ?: now.also { exitStartedAtMs = it }
                    if (now - start >= VEHICLE_EXIT_DURATION_MS) {
                        inVehicle = false
                        enterStartedAtMs = null
                    }
                } else {
                    // Any above-floor sample resets the exit clock so
                    // a red light doesn't bleed into "trip over".
                    exitStartedAtMs = null
                }
            }
            inVehicle
        }.distinctUntilChanged()
    }

    // While armed: wait out the grace window, then every POLL_INTERVAL_MS
    // check the foreground app. Beep while it isn't a nav app. Pause
    // while it is. delay() cooperates with cancellation, so the outer
    // collect cancelling this job cleanly stops the loop.
    private suspend fun runBeepLoop() {
        val armedAt = System.currentTimeMillis()
        delay(GRACE_MS)

        var wasBeeping = false
        while (currentCoroutineContext()[Job]?.isActive != false) {
            val fg = foregroundApp.currentForegroundPackage()
            val isNav = foregroundApp.isNavigationApp(fg)
            val shouldBeep = !isNav
            if (shouldBeep && !wasBeeping) {
                Timber.d(
                    "DistractionGuard: beep on (fg=%s, armed for %d ms)",
                    fg, System.currentTimeMillis() - armedAt,
                )
                alertPlayer.startBeeping()
                wasBeeping = true
            } else if (!shouldBeep && wasBeeping) {
                Timber.d("DistractionGuard: beep off (nav app %s foreground)", fg)
                alertPlayer.stopBeeping()
                wasBeeping = false
            }
            delay(POLL_INTERVAL_MS)
        }
    }

    private companion object {
        // Screen-on must persist this long before any beep. Covers
        // notifications that briefly wake the screen + pocket unlocks
        // that go straight back off.
        const val GRACE_MS = 5_000L

        // How often the fg-app check runs while beeping. 2 s is fast
        // enough that flipping to nav feels instant without hammering
        // UsageStats.
        const val POLL_INTERVAL_MS = 2_000L

        // Vehicle-mode enter threshold. 7 m/s ≈ 25 km/h — well above
        // walking (≤ 2 m/s), jogging (≤ 4 m/s), and casual cycling
        // (≤ 5–6 m/s), low enough to still catch urban crawl traffic.
        const val VEHICLE_ENTER_MPS = 7.0f

        // How long continuously above the enter threshold before we
        // commit to "vehicle mode". 15 s rules out a downhill sprint
        // or a scooter burst — it takes a sustained vehicular run.
        const val VEHICLE_ENTER_DURATION_MS = 15_000L

        // Vehicle-mode exit threshold — the floor below which we
        // start the "trip over" clock. 1.4 m/s ≈ 5 km/h: a car
        // creeping forward in traffic stays above this, a parked
        // or walking-off user does not.
        const val VEHICLE_EXIT_MPS = 1.4f

        // How long continuously below the exit threshold before we
        // release vehicle mode. Much shorter than DrivingModeDetector's
        // 2-minute equivalent on purpose — the user explicitly asked
        // that the distraction alert stop the moment they stop driving,
        // not two minutes later when they've already walked into the
        // building. 10 s is long enough to outlast a normal red light
        // while still feeling snappy when the trip really ended.
        const val VEHICLE_EXIT_DURATION_MS = 10_000L

        // Tick cadence for the vehicle-mode emitter. Fast enough that
        // the "we just slowed to a stop" transition fires within half
        // a second; slow enough to be negligible on battery.
        const val TICK_MS = 500L
    }
}
