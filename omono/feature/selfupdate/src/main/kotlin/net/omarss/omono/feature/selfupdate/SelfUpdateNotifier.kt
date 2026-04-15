package net.omarss.omono.feature.selfupdate

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import dagger.hilt.android.qualifiers.ApplicationContext
import net.omarss.omono.core.notification.OmonoNotificationChannels
import net.omarss.omono.core.notification.R as NotificationR
import javax.inject.Inject
import javax.inject.Singleton

// Posts the "Update available" notification. Kept separate from the
// feature-host notification controller because the self-update channel
// has a different importance profile (DEFAULT, not LOW — the user wants
// to know) and is never ongoing.
@Singleton
class SelfUpdateNotifier @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    fun ensureChannel() {
        val manager = context.getSystemService<NotificationManager>() ?: return
        if (manager.getNotificationChannel(OmonoNotificationChannels.SELF_UPDATE_CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            OmonoNotificationChannels.SELF_UPDATE_CHANNEL_ID,
            OmonoNotificationChannels.SELF_UPDATE_CHANNEL_NAME,
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "Notifies when a new omono build is available"
            setShowBadge(true)
            enableVibration(false)
        }
        manager.createNotificationChannel(channel)
    }

    // Lint can't see through the runtime permission guard on Android
    // 13+; the early return above handles the denied case, so the
    // suppression is safe.
    @SuppressLint("MissingPermission")
    fun notifyUpdateAvailable(info: UpdateInfo) {
        ensureChannel()
        if (!hasPostNotificationPermission()) return

        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?.apply { addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP) }
        val pending = launch?.let {
            PendingIntent.getActivity(
                context,
                0,
                it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }

        val body = info.cumulativeChangelog.take(3).joinToString("\n")
            .ifBlank { "Tap to download and install." }

        val builder = NotificationCompat.Builder(
            context,
            OmonoNotificationChannels.SELF_UPDATE_CHANNEL_ID,
        )
            .setSmallIcon(NotificationR.drawable.ic_notification_small)
            .setContentTitle("omono ${info.latest.version} available")
            .setContentText(info.cumulativeChangelog.firstOrNull() ?: "Tap to install.")
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)

        pending?.let { builder.setContentIntent(it) }
        NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, builder.build())
    }

    fun cancel() {
        NotificationManagerCompat.from(context).cancel(NOTIFICATION_ID)
    }

    private fun hasPostNotificationPermission(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    private companion object {
        const val NOTIFICATION_ID: Int = 9090
    }
}
