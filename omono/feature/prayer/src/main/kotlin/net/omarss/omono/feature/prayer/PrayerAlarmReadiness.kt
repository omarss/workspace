package net.omarss.omono.feature.prayer

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService

// Alarm audio is independent of notification permission. These checks expose
// restrictions honestly; a successful MediaPlayer start is not proof of sound.
data class PrayerAlarmReadiness(
    val exactAllowed: Boolean = false,
    val notificationsAllowed: Boolean = false,
    val dndAllowsAlarms: Boolean = false,
    val fixedVolume: Boolean = false,
    val alarmVolume: Int = 0,
    val maximumVolume: Int = 0,
    val fullScreenAllowed: Boolean = true,
)

fun checkPrayerAlarmReadiness(context: Context, scheduler: PrayerScheduler): PrayerAlarmReadiness {
    val audio = context.getSystemService<AudioManager>()
    val manager = context.getSystemService<NotificationManager>()
    val filter = manager?.currentInterruptionFilter ?: NotificationManager.INTERRUPTION_FILTER_UNKNOWN
    val policy = runCatching { manager?.notificationPolicy }.getOrNull()
    val dndAllows = when (filter) {
        NotificationManager.INTERRUPTION_FILTER_ALL, NotificationManager.INTERRUPTION_FILTER_ALARMS -> true
        NotificationManager.INTERRUPTION_FILTER_PRIORITY -> Build.VERSION.SDK_INT >= 28 && policy != null &&
            policy.priorityCategories and NotificationManager.Policy.PRIORITY_CATEGORY_ALARMS != 0
        else -> false
    }
    val granted = Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(
        context, Manifest.permission.POST_NOTIFICATIONS,
    ) == PackageManager.PERMISSION_GRANTED
    return PrayerAlarmReadiness(
        exactAllowed = scheduler.canScheduleExactly(),
        notificationsAllowed = granted && NotificationManagerCompat.from(context).areNotificationsEnabled(),
        dndAllowsAlarms = dndAllows,
        fixedVolume = audio?.isVolumeFixed ?: true,
        alarmVolume = audio?.getStreamVolume(AudioManager.STREAM_ALARM) ?: 0,
        maximumVolume = audio?.getStreamMaxVolume(AudioManager.STREAM_ALARM) ?: 0,
        fullScreenAllowed = Build.VERSION.SDK_INT < 34 || manager?.canUseFullScreenIntent() == true,
    )
}
