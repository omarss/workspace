package net.omarss.omono.core.service

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import net.omarss.omono.core.notification.OmonoNotificationController
import net.omarss.omono.core.notification.R as NotificationR
import timber.log.Timber
import javax.inject.Inject

// The single foreground service that hosts every enabled OmonoFeature.
//
// Lifecycle:
//   start  -> startForeground with a placeholder notification, then for
//             each registered feature: launch a coroutine that collects
//             feature.start(scope) into the shared state holder and
//             refreshes the notification on every update.
//   stop   -> cancel the per-feature jobs, drop foreground, stopSelf.
//
// State is written to FeatureHostStateHolder so the UI layer can observe
// it without binding to this service.
@AndroidEntryPoint
class FeatureHostService : LifecycleService() {

    @Inject lateinit var registry: FeatureRegistry
    @Inject lateinit var notifications: OmonoNotificationController
    @Inject lateinit var stateHolder: FeatureHostStateHolder

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
        stateHolder.setRunning(true)

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
            stateHolder.states.collect { snapshot ->
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
                stateHolder.updateState(feature.id, state)
            }
        }
        featureJobs[feature.id] = job
    }

    private fun stopAllFeatures() {
        if (featureJobs.isNotEmpty()) Timber.i("Stopping %d feature(s)", featureJobs.size)
        featureJobs.values.forEach { it.cancel() }
        featureJobs.clear()
        registry.all().forEach { runCatching { it.stop() } }
        stateHolder.clearStates()
        stateHolder.setRunning(false)
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

    private fun buildNotification() = buildNotificationFrom(stateHolder.states.value)

    private fun buildNotificationFrom(snapshot: Map<FeatureId, FeatureState>): android.app.Notification {
        // Sort so the same feature always sits on the same line across
        // emissions — keeps the notification stable instead of jumping
        // between "speed first, spending second" and vice versa as
        // different features happen to emit first.
        val lines = snapshot.entries
            .sortedBy { it.key.value }
            .map { it.value.summary }

        return notifications.buildOngoing(
            context = this,
            title = "Omono",
            subText = summarySubText(snapshot),
            bodyLines = lines,
            contentIntent = openAppIntent(),
            actions = listOf(buildStopAction()),
        )
    }

    // Short status word that sits next to the app name in the
    // collapsed notification header. Active > Waiting > Error > Idle
    // so the user sees the most interesting state when multiple
    // features are running at once.
    private fun summarySubText(snapshot: Map<FeatureId, FeatureState>): String? {
        if (snapshot.isEmpty()) return null
        val states = snapshot.values
        return when {
            states.any { it is FeatureState.Active } -> "Tracking"
            states.any { it is FeatureState.Error } ->
                (states.first { it is FeatureState.Error } as FeatureState.Error).summary
            states.any { it is FeatureState.Idle } -> "Idle"
            else -> null
        }
    }

    private fun buildStopAction(): NotificationCompat.Action {
        val intent = Intent(this, FeatureHostService::class.java).setAction(ACTION_STOP)
        val pending = PendingIntent.getService(
            this,
            STOP_REQUEST_CODE,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Action.Builder(
            NotificationR.drawable.ic_notification_stop,
            "Stop",
            pending,
        ).build()
    }

    // Tap on the notification opens the launcher activity. Resolving it
    // dynamically avoids a hard reference from :core to :app.
    private fun openAppIntent(): PendingIntent? {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName) ?: return null
        return PendingIntent.getActivity(
            this,
            OPEN_APP_REQUEST_CODE,
            launchIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    companion object {
        const val ACTION_START: String = "net.omarss.omono.action.START"
        const val ACTION_STOP: String = "net.omarss.omono.action.STOP"

        private const val OPEN_APP_REQUEST_CODE = 0
        private const val STOP_REQUEST_CODE = 1

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
