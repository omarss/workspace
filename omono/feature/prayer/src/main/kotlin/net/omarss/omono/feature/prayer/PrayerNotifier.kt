package net.omarss.omono.feature.prayer

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.getSystemService
import dagger.hilt.android.qualifiers.ApplicationContext
import net.omarss.omono.core.notification.OmonoNotificationChannels
import timber.log.Timber
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

// Posts the per-prayer notification. One channel for all prayers so
// users can manage sound / vibration / DND as a single bucket; the
// content text switches between the five prayers' display names.
@Singleton
class PrayerNotifier @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val timeFormatter: DateTimeFormatter by lazy {
        DateTimeFormatter.ofPattern("HH:mm", Locale.getDefault())
            .withZone(ZoneId.systemDefault())
    }

    fun ensureChannel() {
        val manager = context.getSystemService<NotificationManager>() ?: return
        if (manager.getNotificationChannel(OmonoNotificationChannels.PRAYER_CHANNEL_ID) != null) {
            return
        }
        val channel = NotificationChannel(
            OmonoNotificationChannels.PRAYER_CHANNEL_ID,
            OmonoNotificationChannels.PRAYER_CHANNEL_NAME,
            // HIGH so the notification posts as heads-up on lock screen
            // and plays the channel-default alert sound for non-Fajr
            // prayers (Fajr uses the AthanPlayer's own stream instead).
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Notifications for the five daily prayers"
            enableVibration(true)
            setShowBadge(true)
        }
        manager.createNotificationChannel(channel)
    }

    fun notify(context: Context, kind: PrayerKind, atEpochMs: Long) {
        ensureChannel()
        val manager = NotificationManagerCompat.from(context)
        val title = when (kind) {
            PrayerKind.Fajr -> "الفجر · Fajr"
            PrayerKind.Sunrise -> "الشروق · Sunrise"
            PrayerKind.Dhuhr -> "الظهر · Dhuhr"
            PrayerKind.Asr -> "العصر · Asr"
            PrayerKind.Maghrib -> "المغرب · Maghrib"
            PrayerKind.Isha -> "العشاء · Isha"
        }
        val formatted = timeFormatter.format(Instant.ofEpochMilli(atEpochMs))
        val notification = NotificationCompat.Builder(
            context,
            OmonoNotificationChannels.PRAYER_CHANNEL_ID,
        )
            .setSmallIcon(net.omarss.omono.core.notification.R.drawable.ic_notification_small)
            .setContentTitle(title)
            .setContentText("Prayer time · $formatted")
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setWhen(atEpochMs)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()

        val notificationId = NOTIFICATION_ID_BASE + kind.ordinal
        runCatching {
            manager.notify(notificationId, notification)
        }.onFailure {
            Timber.w(it, "PrayerNotifier: post failed (kind=%s)", kind)
        }
    }

    private companion object {
        const val NOTIFICATION_ID_BASE = 7400
    }
}
