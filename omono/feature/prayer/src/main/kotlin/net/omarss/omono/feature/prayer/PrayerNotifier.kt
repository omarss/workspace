package net.omarss.omono.feature.prayer

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
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

    fun notify(
        context: Context,
        kind: PrayerKind,
        atEpochMs: Long,
        fullScreenChallenge: Boolean = false,
    ) {
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
        val builder = NotificationCompat.Builder(
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

        // Fajr + challenge-to-stop is on → attach a full-screen-intent
        // that launches the challenge activity over the lock screen.
        // Android uses this as a heads-up fallback on unlocked screens
        // and as a direct-launch trigger on locked screens.
        if (fullScreenChallenge) {
            val fsi = challengeFullScreenIntent(context)
            if (fsi != null) {
                builder.setFullScreenIntent(fsi, true)
                builder.setContentIntent(fsi)
                // Ongoing so the user can't swipe it away before the
                // gate has been passed — only the challenge activity
                // dismisses it (via manager.cancel after success).
                builder.setOngoing(true)
            }
        }

        val notificationId = NOTIFICATION_ID_BASE + kind.ordinal
        runCatching {
            manager.notify(notificationId, builder.build())
        }.onFailure {
            Timber.w(it, "PrayerNotifier: post failed (kind=%s)", kind)
        }
    }

    // Dismiss the Fajr-challenge notification — called by the
    // AthanChallengeActivity once the user clears the gate, so the
    // notification shade cleans up along with the athan stopping.
    fun cancel(context: Context, kind: PrayerKind) {
        val manager = NotificationManagerCompat.from(context)
        runCatching { manager.cancel(NOTIFICATION_ID_BASE + kind.ordinal) }
    }

    // Builds a PendingIntent that opens the challenge activity.
    // Uses an explicit ComponentName so the feature/prayer module
    // doesn't need a compile-time reference to the app module's
    // activity class. The fully-qualified name is stable — if we
    // ever rename the activity we update the string here and the
    // manifest in lock-step.
    private fun challengeFullScreenIntent(context: Context): PendingIntent? {
        val intent = Intent().apply {
            component = ComponentName(
                context.packageName,
                CHALLENGE_ACTIVITY_CLASS,
            )
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        }
        return runCatching {
            PendingIntent.getActivity(
                context,
                CHALLENGE_REQUEST_CODE,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }.getOrNull()
    }

    private companion object {
        const val NOTIFICATION_ID_BASE = 7400
        const val CHALLENGE_REQUEST_CODE = 7402
        const val CHALLENGE_ACTIVITY_CLASS =
            "net.omarss.omono.ui.prayer.challenge.AthanChallengeActivity"
    }
}
