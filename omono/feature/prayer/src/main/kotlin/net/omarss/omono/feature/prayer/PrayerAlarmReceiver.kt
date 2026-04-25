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
import timber.log.Timber
import java.time.LocalDate
import java.time.ZoneId
import javax.inject.Inject

// Wakes on each scheduled prayer time. Responsibilities:
//   1. Post the per-prayer notification (unless the user disabled it).
//   2. If this is Fajr and the athan setting is on, play a random
//      recording from the athans directory (or the default alarm
//      sound if the dir is empty).
//   3. Reschedule the *next day's* prayers once tomorrow rolls in —
//      we only queue today's upcoming alarms at a time, so we need
//      to refresh the queue after each fire.
@AndroidEntryPoint
class PrayerAlarmReceiver : BroadcastReceiver() {

    @Inject lateinit var settings: PrayerSettingsRepository
    @Inject lateinit var locationCache: PrayerLocationCache
    @Inject lateinit var athanPlayer: AthanPlayer
    @Inject lateinit var notifier: PrayerNotifier
    @Inject lateinit var scheduler: PrayerScheduler

    override fun onReceive(context: Context, intent: Intent) {
        val kindName = intent.getStringExtra(PrayerScheduler.EXTRA_KIND) ?: return
        val kind = runCatching { PrayerKind.valueOf(kindName) }.getOrNull() ?: return
        val atEpochMs = intent.getLongExtra(PrayerScheduler.EXTRA_EPOCH_MS, 0L)
        Timber.i("PrayerAlarmReceiver: firing for %s at %d", kind, atEpochMs)

        // Hold the device awake briefly so the coroutine below can
        // finish posting the notification and starting audio before
        // the CPU goes back to sleep. BroadcastReceiver's pending
        // result is the standard pattern here.
        val pending = goAsync()
        val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())
        scope.launch {
            try {
                val snap = settings.snapshot.first()

                val playingAthanForFajr = shouldPlayAthan(kind, snap)
                if (snap.notifyEachPrayer || playingAthanForFajr) {
                    notifier.notify(
                        context = context,
                        kind = kind,
                        atEpochMs = atEpochMs,
                        // Full-screen-intent only for Fajr, only when
                        // the user has opted into the challenge gate.
                        fullScreenChallenge = playingAthanForFajr &&
                            snap.requireChallengeToStop,
                    )
                }
                if (playingAthanForFajr) {
                    athanPlayer.play(snap.athanSelection)
                }

                // Refresh the schedule. Compute tomorrow's day if the
                // firing prayer was today's last one (isha); otherwise
                // just re-emit today's remaining times so a reboot or
                // user setting change keeps the queue consistent.
                val fix = locationCache.last.first()
                if (fix != null) {
                    val today = LocalDate.now(ZoneId.systemDefault())
                    val day = PrayerTimesCalculator.computeDay(
                        latitude = fix.latitude,
                        longitude = fix.longitude,
                        date = today,
                        settings = snap,
                    )
                    scheduler.schedule(day)
                    // And always queue tomorrow's Fajr so a user who
                    // never opens the app still gets the next dawn
                    // alarm without the app needing to be resident.
                    val tomorrow = PrayerTimesCalculator.computeDay(
                        latitude = fix.latitude,
                        longitude = fix.longitude,
                        date = today.plusDays(1),
                        settings = snap,
                    )
                    scheduler.schedule(tomorrow)
                }
            } catch (t: Throwable) {
                Timber.w(t, "PrayerAlarmReceiver: post-alarm work failed")
            } finally {
                pending.finish()
            }
        }
    }
}
