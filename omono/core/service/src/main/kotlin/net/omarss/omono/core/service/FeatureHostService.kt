package net.omarss.omono.core.service

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.omarss.omono.core.notification.OmonoNotificationController
import timber.log.Timber
import javax.inject.Inject

// The single foreground service that hosts every enabled OmonoFeature.
//
// Lifecycle:
//   start  -> startForeground with a placeholder notification, then for
//             each registered feature: launch a coroutine that collects
//             feature.start(scope) into the aggregated state map and
//             refreshes the notification on every update.
//   stop   -> cancel the per-feature jobs (each feature's start() scope
//             is cancelled), then stopSelf.
@AndroidEntryPoint
class FeatureHostService : LifecycleService() {

    @Inject lateinit var registry: FeatureRegistry
    @Inject lateinit var notifications: OmonoNotificationController

    // FeatureId -> latest summary line. StateFlow gives us coalesced
    // updates so a burst of fast emits only redraws the notification once
    // per pass through the main loop.
    private val states = MutableStateFlow<Map<FeatureId, String>>(emptyMap())

    private val featureJobs = mutableMapOf<FeatureId, Job>()
    private var started = false

    override fun onCreate() {
        super.onCreate()
        notifications.ensureChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACTION_STOP -> {
                stopAllFeatures()
                ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            else -> ensureStarted()
        }
        return START_STICKY
    }

    private fun ensureStarted() {
        if (started) return
        started = true

        // Promote to foreground BEFORE launching feature collectors —
        // Android requires startForeground within 5s of startForegroundService.
        ServiceCompat.startForeground(
            this,
            OmonoNotificationController.NOTIFICATION_ID,
            buildNotification(),
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
            } else {
                0
            },
        )

        // Re-render the notification whenever any feature emits a new state.
        lifecycleScope.launch {
            states.collect { snapshot ->
                postNotificationSafely(buildNotificationFrom(snapshot))
            }
        }

        registry.all()
            .filter { it.metadata.defaultEnabled }
            .forEach(::startFeature)
    }

    private fun startFeature(feature: OmonoFeature) {
        if (featureJobs.containsKey(feature.id)) return
        Timber.i("Starting feature %s", feature.id.value)
        val job = lifecycleScope.launch {
            feature.start(this).collect { state ->
                states.update { it + (feature.id to state.summary) }
            }
        }
        featureJobs[feature.id] = job
    }

    private fun stopAllFeatures() {
        if (featureJobs.isNotEmpty()) Timber.i("Stopping %d feature(s)", featureJobs.size)
        featureJobs.values.forEach { it.cancel() }
        featureJobs.clear()
        registry.all().forEach { runCatching { it.stop() } }
        states.value = emptyMap()
        started = false
    }

    override fun onDestroy() {
        stopAllFeatures()
        super.onDestroy()
    }

    // POST_NOTIFICATIONS may be absent on Android 13+; we still want the
    // service to keep collecting state — the user just won't see updates
    // until they grant the permission. The try/catch covers the race where
    // the user revokes mid-run.
    private fun postNotificationSafely(notification: android.app.Notification) {
        val manager = NotificationManagerCompat.from(this)
        if (!manager.areNotificationsEnabled()) return
        try {
            manager.notify(OmonoNotificationController.NOTIFICATION_ID, notification)
        } catch (security: SecurityException) {
            Timber.w(security, "POST_NOTIFICATIONS not granted; suppressing update")
        }
    }

    private fun buildNotification() = buildNotificationFrom(states.value)

    private fun buildNotificationFrom(snapshot: Map<FeatureId, String>) =
        notifications.buildOngoing(
            context = this,
            title = "Omono",
            bodyLines = snapshot.values.toList(),
            contentIntent = openAppIntent(),
        )

    // Tap on the notification opens the launcher activity, whatever it is.
    // Resolving it dynamically avoids a hard reference from :core to :app.
    private fun openAppIntent(): PendingIntent? {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName) ?: return null
        return PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    companion object {
        const val ACTION_START: String = "net.omarss.omono.action.START"
        const val ACTION_STOP: String = "net.omarss.omono.action.STOP"

        fun start(context: Context) {
            val intent = Intent(context, FeatureHostService::class.java).setAction(ACTION_START)
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            val intent = Intent(context, FeatureHostService::class.java).setAction(ACTION_STOP)
            context.startService(intent)
        }
    }
}
