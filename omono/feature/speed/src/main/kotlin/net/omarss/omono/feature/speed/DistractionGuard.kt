package net.omarss.omono.feature.speed

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Beeps when the user is actively using the phone for something other
// than navigation while driving.
//
// The previous version treated "screen on" as proof of use — that
// over-fired on notifications that briefly wake the screen, and
// misfired on drivers legitimately using Google Maps / Waze. This
// version adds two checks:
//
//   * Grace window (GRACE_MS). The screen must stay on continuously
//     for this long before the loop starts. Catches pocket-unlocks
//     and notification wakes that settle back to screen-off.
//   * Navigation-app whitelist via UsageStatsManager. If the
//     foreground app is a recognised driver navigation app, beeping
//     pauses. When the user flips back to non-nav (or home screen),
//     beeping resumes.
//
// UsageStats permission is optional; without it the detector reports
// null foreground and the guard treats "non-nav" conservatively (the
// old screen-on-only behaviour). The settings UI surfaces the
// permission status so the user can grant it in one tap.
@Singleton
class DistractionGuard @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val settings: SpeedSettingsRepository,
    private val alertPlayer: SpeedAlertPlayer,
    private val driving: DrivingModeDetector,
    private val foregroundApp: ForegroundAppDetector,
) {

    private var beepLoopJob: Job? = null

    fun attach(scope: CoroutineScope) {
        scope.launch {
            // Five signals × combine(): driving, screen on, setting
            // enabled, proximity uncovered (phone not face-down / in
            // pocket), not currently on a call. Armed only when all
            // align — any one of them tipping false stops the loop
            // immediately via distinctUntilChanged + the else branch.
            combine(
                driving.isDriving,
                context.screenOnFlow(),
                settings.alertOnPhoneUseWhileDriving,
                context.proximityCoveredFlow(),
                context.inCallFlow(),
            ) { isDriving, screenOn, enabled, proxCovered, inCall ->
                enabled && isDriving && screenOn && !proxCovered && !inCall
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
    }
}
