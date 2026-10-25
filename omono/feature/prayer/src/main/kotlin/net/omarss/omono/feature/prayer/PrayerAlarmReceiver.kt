package net.omarss.omono.feature.prayer

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import timber.log.Timber
import javax.inject.Inject

@AndroidEntryPoint
class PrayerAlarmReceiver : BroadcastReceiver() {
    @Inject lateinit var settings: PrayerSettingsRepository
    @Inject lateinit var notifier: PrayerNotifier
    @Inject lateinit var coordinator: PrayerAlarmCoordinator
    @Inject lateinit var checkpoints: PrayerAlarmCheckpoints

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != PrayerScheduler.ACTION_PRAYER) return
        val kind = intent.getStringExtra(PrayerScheduler.EXTRA_KIND)
            ?.let { runCatching { PrayerKind.valueOf(it) }.getOrNull() } ?: return
        val at = intent.getLongExtra(PrayerScheduler.EXTRA_EPOCH_MS, 0L)
        val test = intent.getBooleanExtra(PrayerScheduler.EXTRA_TEST, false)
        // Fajr audio starts independently of diagnostics, DataStore reads, or
        // rescheduling. Those must never consume the broadcast's start window.
        val audioAlarm = test || kind == PrayerKind.Fajr
        val started = audioAlarm && PrayerKeepAliveService.play(context, kind, at, test)
        val pending = goAsync()
        CoroutineScope(Dispatchers.Default + SupervisorJob()).launch {
            try {
                withTimeout(8_000) {
                    checkpoints.received(kind, at, test)
                    if (audioAlarm && !started) {
                        checkpoints.playback("FAILED: Android refused to start alarm playback", test, at)
                    } else if (!audioAlarm && settings.snapshot.first().notifyEachPrayer) {
                        notifier.notify(context, kind, at)
                    }
                    coordinator.repair("alarm received")
                }
            } catch (e: Exception) {
                Timber.e(e, "PrayerAlarmReceiver: delivery failed for %s", kind)
            } finally {
                pending.finish()
            }
        }
    }
}
