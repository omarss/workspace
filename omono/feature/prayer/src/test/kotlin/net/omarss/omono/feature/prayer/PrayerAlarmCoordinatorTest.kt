package net.omarss.omono.feature.prayer

import android.app.Application
import android.app.AlarmManager
import android.content.Context
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.Before
import androidx.datastore.preferences.core.edit
import net.omarss.omono.core.data.omonoDataStore
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.time.LocalDate

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PrayerAlarmCoordinatorTest {
    private val context: Application = RuntimeEnvironment.getApplication()
    private val settings = PrayerSettingsRepository(context)
    private val location = PrayerLocationCache(context)
    private val scheduler = PrayerScheduler(context)
    private val checkpoints = PrayerAlarmCheckpoints(context)
    private val coordinator = PrayerAlarmCoordinator(settings, location, scheduler, checkpoints)

    @Before
    fun resetPreferences() = runBlocking {
        context.omonoDataStore.edit { it.clear() }
        org.robolectric.shadows.ShadowAlarmManager.setCanScheduleExactAlarms(true)
        Unit
    }

    @Test
    fun `repair without a saved location reports the blocker`() = runBlocking {
        coordinator.repair()
        assertTrue(checkpoints.state.first().scheduleStatus.startsWith("No saved location"))
    }

    @Test
    fun `restoring alarms replaces cleared OS alarms using saved location`() = runBlocking {
        location.save(24.7136, 46.6753)
        coordinator.repair("boot")
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        assertEquals(6, shadowOf(manager).scheduledAlarms.size)
        val now = System.currentTimeMillis()
        val expected = nextPrayerOccurrences((0L..1L).map {
            PrayerTimesCalculator.computeDay(24.7136, 46.6753, LocalDate.now().plusDays(it))
        }, now)
        assertEquals(expected.map { it.atEpochMs / 1000 }, shadowOf(manager).scheduledAlarms.map { it.triggerAtTime / 1000 }.sorted())
        scheduler.cancelAll()
        assertEquals(0, shadowOf(manager).scheduledAlarms.size)
        coordinator.repair("package replaced")
        assertEquals(6, shadowOf(manager).scheduledAlarms.size)
        assertTrue(checkpoints.state.first().scheduleStatus.contains("package replaced"))
    }

    @Test
    fun `audio start is recorded without claiming the user heard it`() = runBlocking {
        val at = System.currentTimeMillis() + 30_000
        checkpoints.testScheduled(at)
        checkpoints.playback("Audio started at maximum alarm volume — confirm it is audible", test = true, testAt = at)
        assertTrue(checkpoints.state.first().testAudioAt > 0)
        assertFalse(checkpoints.state.first().testStatus.contains("confirmed by you"))
        checkpoints.confirmTestHeard()
        checkpoints.playback("Stopped", test = true, testAt = at)
        assertEquals("Audibility confirmed by you", checkpoints.state.first().testStatus)
    }

    @Test
    fun `confirmation cannot pass a test that never started audio`() = runBlocking {
        checkpoints.testScheduled(System.currentTimeMillis() + 30_000)
        checkpoints.confirmTestHeard()
        assertEquals(0L, checkpoints.state.first().testAudioAt)
        assertFalse(checkpoints.state.first().testStatus.contains("confirmed by you"))
        checkpoints.testCancelled()
        assertEquals(0L, checkpoints.state.first().testAt)
    }
    @Test
    fun `preview or previous alarm cannot pass a newly scheduled timed test`() = runBlocking {
        val at = System.currentTimeMillis() + 30_000
        checkpoints.testScheduled(at)
        checkpoints.playback("Audio started", test = true, testAt = at - 30_000)
        assertEquals(0L, checkpoints.state.first().testAudioAt)
        checkpoints.confirmTestHeard()
        assertFalse(checkpoints.state.first().testStatus.contains("confirmed by you"))
    }

}
