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

data class PrayerScheduleResult(
    val scheduled: List<PrayerTime>,
    val exact: Boolean,
    val failures: List<String>,
)

// One PendingIntent per prayer: select its earliest future occurrence across
// both days BEFORE replacing alarms. Scheduling tomorrow separately replaces
// today's alarms because PendingIntent identity does not include extras.
internal fun nextPrayerOccurrences(days: List<PrayerDayTimes>, now: Long): List<PrayerTime> =
    days.flatMap { it.times }.filter { it.atEpochMs > now }
        .groupBy { it.kind }.values.map { times -> times.minBy { it.atEpochMs } }
        .sortedBy { it.atEpochMs }

@Singleton
class PrayerScheduler @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    private val alarms get() = context.getSystemService<AlarmManager>()

    fun canScheduleExactly(): Boolean = alarms?.let {
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S || it.canScheduleExactAlarms()
    } ?: false

    @Synchronized
    fun schedule(days: List<PrayerDayTimes>, now: Long = System.currentTimeMillis()): PrayerScheduleResult {
        val manager = alarms ?: return PrayerScheduleResult(emptyList(), false, listOf("Alarm service unavailable"))
        val next = nextPrayerOccurrences(days, now).associateBy { it.kind }
        val scheduled = mutableListOf<PrayerTime>()
        val failures = mutableListOf<String>()
        val exact = canScheduleExactly()
        PrayerKind.entries.forEach { kind ->
            val time = next[kind]
            if (time == null) {
                cancel(kind)
            } else {
                runCatching { scheduleTime(manager, time, requestCode(kind), exact) }
                    .onSuccess { scheduled += time }
                    .onFailure {
                        failures += "${kind.name}: ${it.javaClass.simpleName}"
                        Timber.e(it, "PrayerScheduler: scheduling %s failed", kind)
                    }
            }
        }
        return PrayerScheduleResult(scheduled.sortedBy { it.atEpochMs }, exact, failures)
    }

    fun scheduleTest(now: Long = System.currentTimeMillis()): PrayerTime {
        check(canScheduleExactly()) { "Allow Alarms & reminders before running the timed test" }
        val time = PrayerTime(PrayerKind.Fajr, now + TEST_DELAY_MS)
        val manager = checkNotNull(alarms) { "Alarm service unavailable" }
        scheduleTime(manager, time, TEST_REQ_CODE, exact = true, test = true)
        return time
    }

    fun cancelTest() = cancelPending(TEST_REQ_CODE)

    fun cancelAll() {
        PrayerKind.entries.forEach { cancel(it) }
        cancelTest()
    }

    private fun cancel(kind: PrayerKind) = cancelPending(requestCode(kind))

    private fun cancelPending(code: Int) {
        val pending = PendingIntent.getBroadcast(
            context, code, baseIntent(), PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE,
        ) ?: return
        alarms?.cancel(pending)
        pending.cancel()
    }

    private fun scheduleTime(
        manager: AlarmManager, time: PrayerTime, code: Int, exact: Boolean, test: Boolean = false,
    ) {
        val pending = PendingIntent.getBroadcast(
            context, code, baseIntent().apply {
                putExtra(EXTRA_KIND, time.kind.name)
                putExtra(EXTRA_EPOCH_MS, time.atEpochMs)
                putExtra(EXTRA_TEST, test)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        if (exact) {
            manager.setAlarmClock(AlarmManager.AlarmClockInfo(time.atEpochMs, launchAppPendingIntent()), pending)
        } else {
            manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time.atEpochMs, pending)
        }
    }

    private fun launchAppPendingIntent(): PendingIntent? {
        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName) ?: return null
        return PendingIntent.getActivity(
            context, SHOW_REQ_CODE, launch, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun baseIntent() = Intent(context, PrayerAlarmReceiver::class.java).setAction(ACTION_PRAYER)
    private fun requestCode(kind: PrayerKind) = REQ_CODE_BASE + kind.ordinal

    companion object {
        const val ACTION_PRAYER = "net.omarss.omono.feature.prayer.ALARM"
        const val EXTRA_KIND = "kind"
        const val EXTRA_EPOCH_MS = "at"
        const val EXTRA_TEST = "test"
        const val TEST_DELAY_MS = 30_000L
        private const val REQ_CODE_BASE = 7300
        private const val SHOW_REQ_CODE = 7299
        private const val TEST_REQ_CODE = 7399
    }
}
