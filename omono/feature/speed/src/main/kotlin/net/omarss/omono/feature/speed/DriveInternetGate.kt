package net.omarss.omono.feature.speed

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Observes driving state + user setting and flips the internet
// governor on each transition. Only reacts to actual changes — a
// steady "not driving" state on app startup doesn't re-enable
// internet the user may have deliberately left off.
//
// The governor itself is a no-op when Shizuku isn't ready, so this
// gate doesn't need to know about readiness — the "enable" call
// during a settings-off flip will still be attempted; failing
// silently is fine because we never disabled in the first place.
@Singleton
class DriveInternetGate @Inject constructor(
    private val settings: SpeedSettingsRepository,
    private val driving: DrivingModeDetector,
    private val governor: InternetGovernor,
) {

    fun attach(scope: CoroutineScope) {
        scope.launch {
            var wasDisabling = false
            combine(
                driving.isDriving,
                settings.disableInternetWhileDriving,
            ) { isDriving, enabled -> isDriving && enabled }
                .distinctUntilChanged()
                .collect { shouldDisable ->
                    when {
                        shouldDisable && !wasDisabling -> {
                            Timber.i("DriveInternetGate: disabling internet (drive start)")
                            governor.disableInternet()
                        }
                        !shouldDisable && wasDisabling -> {
                            Timber.i("DriveInternetGate: re-enabling internet (drive end)")
                            governor.enableInternet()
                        }
                    }
                    wasDisabling = shouldDisable
                }
        }
    }

    // Called from SpeedFeature.stop(): if we were mid-drive when the
    // user tapped stop, the coroutine would be cancelled before the
    // drive-end transition fires. Explicit re-enable here guarantees
    // we never leave the user offline after a manual stop.
    suspend fun ensureEnabledOnStop() {
        governor.enableInternet()
    }
}
