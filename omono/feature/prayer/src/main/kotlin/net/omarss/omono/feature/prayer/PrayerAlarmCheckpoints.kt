package net.omarss.omono.feature.prayer

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

data class PrayerAlarmCheckpointState(
    val scheduledAt: Long = 0,
    val nextAlarmAt: Long = 0,
    val nextAlarmKind: String = "",
    val scheduleStatus: String = "Not checked yet",
    val receivedAt: Long = 0,
    val receivedKind: String = "",
    val playbackAt: Long = 0,
    val playbackStatus: String = "No playback recorded",
    val testAt: Long = 0,
    val testStatus: String = "No timed test run",
    val testAudioAt: Long = 0,
)

// Durable checkpoints distinguish a scheduling failure from delivery or audio
// failure, including after the process exits or the device reboots.
@Singleton
class PrayerAlarmCheckpoints @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    val state = context.omonoDataStore.data.map { p ->
        PrayerAlarmCheckpointState(
            p[SCHEDULED] ?: 0, p[NEXT_AT] ?: 0, p[NEXT_KIND].orEmpty(), p[SCHEDULE_STATUS] ?: "Not checked yet",
            p[RECEIVED] ?: 0, p[RECEIVED_KIND].orEmpty(), p[PLAYBACK_AT] ?: 0,
            p[PLAYBACK_STATUS] ?: "No playback recorded", p[TEST_AT] ?: 0, p[TEST_STATUS] ?: "No timed test run", p[TEST_AUDIO_AT] ?: 0,
        )
    }

    suspend fun scheduled(result: PrayerScheduleResult, reason: String) {
        context.omonoDataStore.edit { p ->
            p[SCHEDULED] = System.currentTimeMillis()
            p[NEXT_AT] = result.scheduled.firstOrNull()?.atEpochMs ?: 0
            p[NEXT_KIND] = result.scheduled.firstOrNull()?.kind?.name.orEmpty()
            p[SCHEDULE_STATUS] = when {
                result.failures.isNotEmpty() -> "Scheduling failed: ${result.failures.joinToString()}"
                result.scheduled.isEmpty() -> "No future alarms scheduled"
                !result.exact -> "Alarms may be late: allow Alarms & reminders"
                else -> "${result.scheduled.size} exact alarms scheduled ($reason)"
            }
        }
    }

    suspend fun schedulingFailed(message: String) {
        context.omonoDataStore.edit { it[SCHEDULE_STATUS] = message }
    }

    suspend fun received(kind: PrayerKind, scheduledAt: Long, test: Boolean) {
        val now = System.currentTimeMillis()
        context.omonoDataStore.edit {
            it[RECEIVED] = now
            it[RECEIVED_KIND] = if (test) "Timed test" else kind.name
            if (test && it[TEST_AT] == scheduledAt) it[TEST_STATUS] = "Received after ${(now - scheduledAt).coerceAtLeast(0) / 1000}s delay; starting audio"
        }
    }

    suspend fun playback(status: String, test: Boolean = false, testAt: Long = 0) {
        context.omonoDataStore.edit {
            it[PLAYBACK_AT] = System.currentTimeMillis()
            it[PLAYBACK_STATUS] = status
            if (test && testAt > 0 && it[TEST_AT] == testAt) {
                if ((it[TEST_CONFIRMED_AT] ?: 0) == 0L) it[TEST_STATUS] = status
                if (status.startsWith("Audio started")) it[TEST_AUDIO_AT] = System.currentTimeMillis()
            }
        }
    }

    suspend fun testScheduled(at: Long) {
        context.omonoDataStore.edit {
            it[TEST_AT] = at
            it[TEST_AUDIO_AT] = 0
            it[TEST_CONFIRMED_AT] = 0
            it[TEST_STATUS] = "Scheduled — lock the screen and listen in 30 seconds"
        }
    }

    suspend fun testFailed(message: String) {
        context.omonoDataStore.edit {
            it[TEST_AT] = 0
            it[TEST_AUDIO_AT] = 0
            it[TEST_CONFIRMED_AT] = 0
            it[TEST_STATUS] = message
        }
    }

    suspend fun testCancelled() {
        context.omonoDataStore.edit {
            it[TEST_AT] = 0
            if ((it[TEST_AUDIO_AT] ?: 0) == 0L) it[TEST_STATUS] = "Timed test cancelled"
        }
    }

    suspend fun confirmTestHeard() {
        context.omonoDataStore.edit {
            if ((it[TEST_AUDIO_AT] ?: 0) > 0) {
                it[TEST_CONFIRMED_AT] = System.currentTimeMillis()
                it[TEST_STATUS] = "Audibility confirmed by you"
            }
        }
    }

    private companion object {
        val SCHEDULED = longPreferencesKey("prayer.check.scheduled")
        val NEXT_AT = longPreferencesKey("prayer.check.next_at")
        val NEXT_KIND = stringPreferencesKey("prayer.check.next_kind")
        val SCHEDULE_STATUS = stringPreferencesKey("prayer.check.schedule_status")
        val RECEIVED = longPreferencesKey("prayer.check.received")
        val RECEIVED_KIND = stringPreferencesKey("prayer.check.received_kind")
        val PLAYBACK_AT = longPreferencesKey("prayer.check.playback_at")
        val PLAYBACK_STATUS = stringPreferencesKey("prayer.check.playback_status")
        val TEST_CONFIRMED_AT = longPreferencesKey("prayer.check.test_confirmed_at")
        val TEST_AUDIO_AT = longPreferencesKey("prayer.check.test_audio_at")
        val TEST_AT = longPreferencesKey("prayer.check.test_at")
        val TEST_STATUS = stringPreferencesKey("prayer.check.test_status")
    }
}
