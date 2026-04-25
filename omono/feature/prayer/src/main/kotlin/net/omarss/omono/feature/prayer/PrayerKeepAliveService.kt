package net.omarss.omono.feature.prayer

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.getSystemService
import dagger.hilt.android.AndroidEntryPoint
import net.omarss.omono.core.notification.OmonoNotificationChannels
import timber.log.Timber

// Always-on background process anchor for reliability mode. AlarmManager
// alarms (even setAlarmClock) can be silenced by aggressive OEM kill
// regimes (Samsung, Xiaomi, Huawei, Oppo, Vivo, …) which routinely
// terminate processes that the user hasn't opened recently. A foreground
// service raises omono out of the killable bucket — once started, the
// system keeps the process resident until the user explicitly stops it.
//
// The service does *no* real work — it just exists to hold the process
// alive so AlarmManager has something to wake to. CPU is essentially
// idle while it runs.
//
// Only spun up when the user opts in via Settings → Prayer → Reliability
// mode. Costs a single low-importance notification in the shade.
@AndroidEntryPoint
class PrayerKeepAliveService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ensureChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
        return START_STICKY
    }

    private fun ensureChannel() {
        val manager = getSystemService<NotificationManager>() ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            CHANNEL_NAME,
            // LOW so the channel is silent + no heads-up; the
            // notification is informational only.
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Background process anchor for prayer alarms"
            setShowBadge(false)
            enableVibration(false)
            enableLights(false)
            setSound(null, null)
        }
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(): android.app.Notification {
        val launch = packageManager.getLaunchIntentForPackage(packageName)
        val tap = launch?.let {
            PendingIntent.getActivity(
                this,
                0,
                it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(net.omarss.omono.core.notification.R.drawable.ic_notification_small)
            .setContentTitle("Prayer alarms active")
            .setContentText("Reliability mode keeps Fajr alarms firing on schedule.")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setShowWhen(false)
            .setContentIntent(tap)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
    }

    companion object {
        // Distinct from the per-prayer notification id range so the
        // keep-alive notification doesn't collide with Fajr alerts.
        const val NOTIFICATION_ID = 7401
        const val CHANNEL_ID = "omono.prayer.keep_alive"
        const val CHANNEL_NAME = "Prayer reliability"

        fun start(context: Context) {
            val intent = Intent(context, PrayerKeepAliveService::class.java)
            runCatching {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            }.onFailure { Timber.w(it, "PrayerKeepAliveService.start failed") }
        }

        fun stop(context: Context) {
            runCatching {
                context.stopService(Intent(context, PrayerKeepAliveService::class.java))
            }.onFailure { Timber.w(it, "PrayerKeepAliveService.stop failed") }
        }
    }
}
