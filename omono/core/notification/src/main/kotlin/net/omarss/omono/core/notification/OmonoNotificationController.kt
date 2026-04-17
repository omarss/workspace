package net.omarss.omono.core.notification

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import androidx.core.app.NotificationCompat
import androidx.core.content.getSystemService
import androidx.core.content.res.ResourcesCompat
import androidx.core.graphics.drawable.toBitmap
import javax.inject.Inject
import javax.inject.Singleton

// Single place that knows how to render the ongoing omono notification.
// Keeping this out of FeatureHostService lets feature modules stay free
// of any direct Notification API knowledge.
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
            // Show the speed + spending detail on the lock screen instead
            // of the generic "omono has a notification" redacted view.
            // Channel-level visibility can only be set at creation time;
            // the per-notification setVisibility(PUBLIC) below is ignored
            // if the channel itself is PRIVATE.
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        manager.createNotificationChannel(channel)
    }

    // Builds the ongoing notification.
    //
    //   title        Prominent top line. Usually "Omono".
    //   subText      Short secondary label rendered to the right of the
    //                app name (e.g. "v0.6.1 · Tracking"). Null hides it.
    //   bodyLines    One string per active feature. The first line is
    //                the collapsed content; InboxStyle shows the full
    //                list when expanded.
    //   contentIntent  Tapping the body opens this intent (normally
    //                  the main activity).
    //   actions      Buttons rendered at the bottom of the notification.
    //                The host service passes a single Stop action.
    fun buildOngoing(
        context: Context,
        title: String,
        subText: String?,
        bodyLines: List<String>,
        contentIntent: PendingIntent?,
        actions: List<NotificationCompat.Action> = emptyList(),
    ): Notification {
        val nonEmptyLines = bodyLines.filter { it.isNotBlank() }
        val firstLine = nonEmptyLines.firstOrNull() ?: "Starting…"

        val style = NotificationCompat.InboxStyle()
        style.setBigContentTitle(title)
        if (subText != null) {
            style.setSummaryText(subText)
        }
        if (nonEmptyLines.isEmpty()) {
            style.addLine("Starting…")
        } else {
            for (line in nonEmptyLines) {
                style.addLine(line)
            }
        }

        val builder = NotificationCompat.Builder(
            context,
            OmonoNotificationChannels.FEATURE_HOST_CHANNEL_ID,
        )
            .setSmallIcon(R.drawable.ic_notification_small)
            .setLargeIcon(loadLargeIcon(context))
            .setColor(BRAND_COLOR)
            .setContentTitle(title)
            .setContentText(firstLine)
            .setSubText(subText)
            .setStyle(style)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setShowWhen(false)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)

        contentIntent?.let { builder.setContentIntent(it) }
        actions.forEach { builder.addAction(it) }

        return builder.build()
    }

    // Rasterises the full-colour omono vector into the 96dp square
    // large-icon slot. Cached on first render so subsequent updates
    // (every GPS tick) reuse the same bitmap instead of re-inflating
    // a vector drawable at 1 Hz.
    private var cachedLargeIcon: Bitmap? = null
    private fun loadLargeIcon(context: Context): Bitmap? {
        cachedLargeIcon?.let { return it }
        val drawable = ResourcesCompat.getDrawable(
            context.resources,
            R.drawable.ic_notification_large,
            context.theme,
        ) ?: return null
        val density = context.resources.displayMetrics.density
        val sizePx = (96 * density).toInt().coerceAtLeast(96)
        val bitmap = drawable.toBitmap(width = sizePx, height = sizePx)
        cachedLargeIcon = bitmap
        return bitmap
    }

    companion object {
        const val NOTIFICATION_ID: Int = 4242

        // omono brand primary. Kept as an Int literal so :core:notification
        // stays free of a res/color dependency for a single constant.
        private val BRAND_COLOR: Int = Color.parseColor("#2563EB")
    }
}
