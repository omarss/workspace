package net.omarss.omono.core.notification

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import androidx.core.app.NotificationCompat
import androidx.core.content.getSystemService
import javax.inject.Inject
import javax.inject.Singleton

// One place that knows how to render ongoing notifications for the host
// service. Keeping this out of FeatureHostService lets feature modules
// stay free of any direct Notification API knowledge.
@Singleton
class OmonoNotificationController @Inject constructor() {

    fun ensureChannel(context: Context) {
        val manager = context.getSystemService<NotificationManager>() ?: return
        if (manager.getNotificationChannel(OmonoNotificationChannels.FEATURE_HOST_CHANNEL_ID) != null) return

        val channel = NotificationChannel(
            OmonoNotificationChannels.FEATURE_HOST_CHANNEL_ID,
            OmonoNotificationChannels.FEATURE_HOST_CHANNEL_NAME,
            // LOW: silent + no heads-up. The notification is informational,
            // not an alert — we don't want it to vibrate every second.
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Persistent display of background trackers"
            setShowBadge(false)
            enableVibration(false)
            enableLights(false)
            setSound(null, null)
        }
        manager.createNotificationChannel(channel)
    }

    fun buildOngoing(
        context: Context,
        title: String,
        bodyLines: List<String>,
        contentIntent: PendingIntent?,
    ): Notification {
        val joined = bodyLines.joinToString(separator = "\n").ifBlank { "Starting…" }
        val firstLine = bodyLines.firstOrNull()?.takeIf { it.isNotBlank() } ?: "Starting…"

        return NotificationCompat.Builder(context, OmonoNotificationChannels.FEATURE_HOST_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentTitle(title)
            .setContentText(firstLine)
            .setStyle(NotificationCompat.BigTextStyle().bigText(joined))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setShowWhen(false)
            .also { builder -> contentIntent?.let { builder.setContentIntent(it) } }
            .build()
    }

    companion object {
        const val NOTIFICATION_ID: Int = 4242
    }
}
