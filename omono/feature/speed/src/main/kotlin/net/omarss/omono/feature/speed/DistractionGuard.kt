package net.omarss.omono.feature.speed

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// When the user is driving AND interacting with the phone (screen on),
// sound a continuous alarm-stream beep until one of the conditions
// becomes false. Designed to make "pick up the phone mid-drive" so
// annoying that you put it down again.
//
// Opt-in via settings.alertOnPhoneUseWhileDriving. Off by default —
// the feature is loud on purpose and shouldn't surprise anyone.
//
// All three input signals are Flow<Boolean>, combined via a single
// collect into a "shouldBeep" decision. distinctUntilChanged keeps
// the alert player from being hammered with redundant start/stop
// calls when only one upstream flow changes.
@Singleton
class DistractionGuard @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val settings: SpeedSettingsRepository,
    private val alertPlayer: SpeedAlertPlayer,
    private val driving: DrivingModeDetector,
) {

    fun attach(scope: CoroutineScope) {
        scope.launch {
            combine(
                driving.isDriving,
                context.screenOnFlow(),
                settings.alertOnPhoneUseWhileDriving,
            ) { isDriving, screenOn, enabled ->
                enabled && isDriving && screenOn
            }
                .distinctUntilChanged()
                .collect { shouldBeep ->
                    if (shouldBeep) {
                        Timber.d("DistractionGuard: beeping on")
                        alertPlayer.startBeeping()
                    } else {
                        Timber.d("DistractionGuard: beeping off")
                        alertPlayer.stopBeeping()
                    }
                }
        }
    }
}
