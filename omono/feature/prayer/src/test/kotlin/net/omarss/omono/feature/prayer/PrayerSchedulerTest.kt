package net.omarss.omono.feature.prayer

import android.app.AlarmManager
import android.app.Application
import android.content.Context
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.time.LocalDate

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class PrayerSchedulerTest {
    private val context: Application = RuntimeEnvironment.getApplication()
    private val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
    private val scheduler = PrayerScheduler(context)

    @Test
    fun `queuing tomorrow must not replace today's upcoming prayer`() {
        val now = System.currentTimeMillis()
        val today = PrayerDayTimes(LocalDate.now(), listOf(PrayerTime(PrayerKind.Dhuhr, now + 60_000)))
        val tomorrow = PrayerDayTimes(LocalDate.now().plusDays(1), listOf(PrayerTime(PrayerKind.Dhuhr, now + 86_400_000)))
        scheduler.schedule(listOf(today, tomorrow), now)
        assertEquals(now + 60_000, shadowOf(manager).scheduledAlarms.minOf { it.triggerAtTime })
    }

    @Test
    fun `cancelAll removes the alarms actually scheduled`() {
        val now = System.currentTimeMillis()
        scheduler.schedule(listOf(PrayerDayTimes(LocalDate.now(), listOf(PrayerTime(PrayerKind.Fajr, now + 60_000)))), now)
        scheduler.cancelAll()
        assertEquals(0, shadowOf(manager).scheduledAlarms.size)
    }
    @Test
    fun `rescheduling selects tomorrow only for prayers that have passed`() {
        val now = System.currentTimeMillis()
        val today = PrayerDayTimes(LocalDate.now(), listOf(
            PrayerTime(PrayerKind.Fajr, now - 60_000), PrayerTime(PrayerKind.Dhuhr, now + 60_000)))
        val tomorrow = PrayerDayTimes(LocalDate.now().plusDays(1), listOf(
            PrayerTime(PrayerKind.Fajr, now + 43_200_000), PrayerTime(PrayerKind.Dhuhr, now + 86_400_000)))
        val result = scheduler.schedule(listOf(today, tomorrow), now)
        assertEquals(listOf(now + 60_000, now + 43_200_000), result.scheduled.map { it.atEpochMs })
        scheduler.schedule(listOf(today, tomorrow), now)
        assertEquals(2, shadowOf(manager).scheduledAlarms.size)
    }

    @Test
    fun `timed test uses its own alarm and can be cancelled independently`() {
        val now = System.currentTimeMillis()
        scheduler.schedule(listOf(PrayerDayTimes(LocalDate.now(), listOf(PrayerTime(PrayerKind.Fajr, now + 60_000)))), now)
        scheduler.scheduleTest(now)
        assertEquals(2, shadowOf(manager).scheduledAlarms.size)
        val testAlarm = shadowOf(manager).scheduledAlarms.minBy { it.triggerAtTime }
        val intent = shadowOf(testAlarm.operation).savedIntent
        assertEquals(true, intent.getBooleanExtra(PrayerScheduler.EXTRA_TEST, false))
        assertEquals(now + 30_000, testAlarm.triggerAtTime)
        scheduler.cancelTest()
        assertEquals(1, shadowOf(manager).scheduledAlarms.size)
    }

    @Test
    @Config(sdk = [33])
    fun `denied exact access is reported and cannot pass the timed exact test`() {
        org.robolectric.shadows.ShadowAlarmManager.setCanScheduleExactAlarms(false)
        val now = System.currentTimeMillis()
        val result = scheduler.schedule(listOf(PrayerDayTimes(LocalDate.now(), listOf(PrayerTime(PrayerKind.Fajr, now + 60_000)))), now)
        assertEquals(false, result.exact)
        assertEquals(1, result.scheduled.size)
        org.junit.Assert.assertThrows(IllegalStateException::class.java) { scheduler.scheduleTest(now) }
    }

}
