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
//   2. Device is currently moving. Uses a deliberately short-lived
//      "moving" gate (1 m/s threshold with a 4 s grace) rather than
//      DrivingModeDetector's 2-minute sticky state, because the user
//      expects the beep to stop the moment they slow down — not two
//      minutes later at a red light.
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
            // The accelerometer-variance "phone in hand" signal used
            // to live here too; it was dropped because it reported
            // "not in hand" for dashboard-mounted phones (where the
            // whole device barely moves even while the user scrolls),
            // which silently suppressed the alert in exactly the
            // situation we want it for. See the class-level comment.
            val silencedFlow: Flow<Boolean> = combine(
                context.proximityCoveredFlow(),
                context.inCallFlow(),
            ) { proxCovered, inCall ->
                proxCovered || inCall
            }

            combine(
                movingNowFlow(),
                context.screenOnFlow(),
                settings.alertOnPhoneUseWhileDriving,
                silencedFlow,
            ) { moving, screenOn, enabled, silenced ->
                enabled && moving && screenOn && !silenced
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

    // Emits `true` while the device has registered speed above
    // MOVING_MPS within the last MOVING_GRACE_MS, `false` otherwise.
    // Driven by a 500 ms ticker combined with the speed StateFlow so a
    // stopped car still transitions to `false` promptly — we can't
    // rely on the GPS callback firing when speed is zero.
    private fun movingNowFlow(): Flow<Boolean> {
        val ticker: Flow<Unit> = flow {
            while (true) {
                emit(Unit)
                delay(TICK_MS)
            }
        }
        var lastMovingMs = Long.MIN_VALUE / 2
        return combine(speedRepository.currentSpeedMps, ticker) { s, _ ->
            val now = System.currentTimeMillis()
            if (s >= MOVING_MPS) lastMovingMs = now
            now - lastMovingMs < MOVING_GRACE_MS
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

        // Speed threshold for "the car is actually moving". 1 m/s is
        // ~3.6 km/h — below that is GPS jitter at a stand-still.
        const val MOVING_MPS = 1.0f

        // How long after the last above-threshold sample we still call
        // "moving". 4 s is long enough to absorb a momentary slowdown
        // (ducking into a turn lane, a bump in the road) and short
        // enough that a genuine stop at a red light releases the alert
        // quickly.
        const val MOVING_GRACE_MS = 4_000L

        // Tick cadence for the movingNow emitter. Fast enough that the
        // "we just slowed to a stop" transition fires within half a
        // second; slow enough to be negligible on battery.
        const val TICK_MS = 500L
    }
}
