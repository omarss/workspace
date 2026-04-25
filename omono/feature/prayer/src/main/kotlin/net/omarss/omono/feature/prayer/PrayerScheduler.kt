package net.omarss.omono.feature.prayer

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.content.getSystemService
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Schedules AlarmManager alarms at each prayer time using the
// `setAlarmClock` API — the same priority that real alarm-clock apps
// use. setAlarmClock is the only AlarmManager path that's:
//   * exempt from Doze (fires at the exact wall-clock time even
//     after the device has been idle for hours, which Fajr always is)
//   * not throttled by app-standby buckets (the 9-minute floor that
//     setExactAndAllowWhileIdle falls into)
//   * surfaced as a real alarm icon on the lock screen, with a
//     show-intent that re-opens the app when tapped.
//
// Falls back to setAndAllowWhileIdle on the rare device that's
// denied SCHEDULE_EXACT_ALARM. The fallback can drift by ±10 min
// but at least still fires through Doze.
//
// Each prayer has a distinct PendingIntent request code so rescheduling
// one (e.g. when the user's location moved) replaces just that prayer's
// alarm without touching the others.
@Singleton
class PrayerScheduler @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val alarms get() = context.getSystemService<AlarmManager>()

    // Replaces today's schedule. Past prayers are skipped (the alarm
    // can't fire in the past anyway) so only upcoming times get queued.
    fun schedule(day: PrayerDayTimes, now: Long = System.currentTimeMillis()) {
        val manager = alarms ?: run {
            Timber.w("PrayerScheduler: no AlarmManager available")
            return
        }
        for (time in day.times) {
            val rc = requestCode(time.kind)
            val existing = PendingIntent.getBroadcast(
                context,
                rc,
                intentFor(time),
                PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE,
            )
            // Drop yesterday's alarm if the PendingIntent lingered.
            existing?.let { runCatching { manager.cancel(it) } }

            if (time.atEpochMs <= now) continue

            val pending = PendingIntent.getBroadcast(
                context,
                rc,
                intentFor(time),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val canExact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
                manager.canScheduleExactAlarms()
            runCatching {
                if (canExact) {
                    // setAlarmClock takes both the firing PendingIntent
                    // and a show-intent that opens when the user taps
                    // the alarm icon on the lock screen.
                    val show = launchAppPendingIntent()
                    val info = AlarmManager.AlarmClockInfo(time.atEpochMs, show)
                    manager.setAlarmClock(info, pending)
                } else {
                    // Inexact fallback — ±10 min drift, but still fires
                    // through Doze. Triggered only when the user has
                    // explicitly denied SCHEDULE_EXACT_ALARM.
                    manager.setAndAllowWhileIdle(
                        AlarmManager.RTC_WAKEUP,
                        time.atEpochMs,
                        pending,
                    )
                }
            }.onFailure { Timber.w(it, "failed to schedule %s", time.kind) }
        }
    }

    // PendingIntent that opens the app when the user taps the alarm
    // clock icon on the lock screen. Uses the package's launch intent
    // so feature/prayer doesn't need a hard dependency on MainActivity.
    private fun launchAppPendingIntent(): PendingIntent? {
        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?: return null
        return PendingIntent.getActivity(
            context,
            SHOW_REQ_CODE,
            launch,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    fun cancelAll() {
        val manager = alarms ?: return
        PrayerKind.entries.forEach { kind ->
            val pi = PendingIntent.getBroadcast(
                context,
                requestCode(kind),
                Intent(context, PrayerAlarmReceiver::class.java),
                PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE,
            )
            pi?.let { runCatching { manager.cancel(it) } }
        }
    }

    private fun intentFor(time: PrayerTime): Intent = Intent(
        context,
        PrayerAlarmReceiver::class.java,
    ).apply {
        // Explicit action so the receiver can filter on intent type
        // should we ever add non-prayer alarms alongside.
        action = ACTION_PRAYER
        putExtra(EXTRA_KIND, time.kind.name)
        putExtra(EXTRA_EPOCH_MS, time.atEpochMs)
    }

    // Stable per-kind request code so rescheduling one prayer replaces
    // the existing alarm instead of stacking.
    private fun requestCode(kind: PrayerKind): Int = REQ_CODE_BASE + kind.ordinal

    companion object {
        const val ACTION_PRAYER = "net.omarss.omono.feature.prayer.ALARM"
        const val EXTRA_KIND = "kind"
        const val EXTRA_EPOCH_MS = "at"
        private const val REQ_CODE_BASE = 7300
        private const val SHOW_REQ_CODE = 7299
    }
}
