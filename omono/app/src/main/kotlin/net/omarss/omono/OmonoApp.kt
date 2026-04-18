package net.omarss.omono

import android.app.Application
import dagger.hilt.android.HiltAndroidApp
import net.omarss.omono.feature.speed.InternetGovernor
import timber.log.Timber
import javax.inject.Inject

@HiltAndroidApp
class OmonoApp : Application() {

    // Shizuku binder listeners are registered app-wide rather than
    // scoped to any ViewModel. Multiple consumers (settings screen +
    // drive gate) read the same readiness flow; Singleton + one-shot
    // start in Application.onCreate means there's only ever one
    // listener set against the Shizuku service.
    @Inject lateinit var internetGovernor: InternetGovernor

    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }
        internetGovernor.start()
    }
}
