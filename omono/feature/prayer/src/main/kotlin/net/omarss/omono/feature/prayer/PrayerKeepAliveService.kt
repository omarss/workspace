package net.omarss.omono.feature.prayer

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.getSystemService
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import timber.log.Timber
import javax.inject.Inject

// The existing prayer service owns playback as well as optional reliability
// mode. Audio must not outlive a receiver without a foreground playback owner.
@AndroidEntryPoint
class PrayerKeepAliveService : Service() {
    @Inject lateinit var player: AthanPlayer
    @Inject lateinit var settings: PrayerSettingsRepository
    @Inject lateinit var notifier: PrayerNotifier
    @Inject lateinit var checkpoints: PrayerAlarmCheckpoints

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var reliability = false
    private var generation = 0
    private var playbackActive = false
    private var playbackStarted = false
    private var currentTest = false
    private var currentAt = 0L
    private var startupWakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        running = true
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                val token = ++generation
                player.stop()
                scope.launch { finishPlayback(token, "Stopped", currentTest, currentAt) }
            }
            ACTION_DISABLE_RELIABILITY -> {
                reliability = false
                if (!playbackActive) stopSelf()
            }
            ACTION_PLAY -> {
                playbackActive = true
                playbackStarted = false
                acquireStartupWakeLock()
                currentTest = intent.getBooleanExtra(PrayerScheduler.EXTRA_TEST, false)
                currentAt = intent.getLongExtra(PrayerScheduler.EXTRA_EPOCH_MS, 0)
                runCatching { showForeground(playback = true, canStop = intent.getBooleanExtra(PrayerScheduler.EXTRA_TEST, false)) }
                    .onSuccess { scope.launch { startPlayback(intent) } }
                    .onFailure { error ->
                        Timber.e(error, "Athan foreground notification failed")
                        scope.launch { finishPlayback(generation, "FAILED: foreground playback permission or service unavailable", currentTest, currentAt) }
                    }
            }
            else -> {
                reliability = true
                showForeground(playback = playbackActive)
            }
        }
        return if (reliability) START_STICKY else START_NOT_STICKY
    }

    private suspend fun startPlayback(intent: Intent) {
        val kind = intent.getStringExtra(PrayerScheduler.EXTRA_KIND)
            ?.let { runCatching { PrayerKind.valueOf(it) }.getOrNull() } ?: PrayerKind.Fajr
        val test = intent.getBooleanExtra(PrayerScheduler.EXTRA_TEST, false)
        val token = ++generation
        val at = intent.getLongExtra(PrayerScheduler.EXTRA_EPOCH_MS, 0)
        try {
            val snap = try {
                withTimeout(3_000) { settings.snapshot.first() }
            } catch (error: Exception) {
                if (error is kotlinx.coroutines.CancellationException && error !is kotlinx.coroutines.TimeoutCancellationException) throw error
                Timber.e(error, "Athan settings unavailable; using bundled Fajr alarm defaults")
                PrayerSettingsSnapshot(reliabilityMode = reliability)
            }
            if (token != generation) return
            reliability = snap.reliabilityMode
            if (!test && !shouldPlayAthan(kind, snap)) {
                if (snap.notifyEachPrayer) {
                    runCatching { notifier.notify(this, kind, intent.getLongExtra(PrayerScheduler.EXTRA_EPOCH_MS, 0)) }
                        .onFailure { Timber.e(it, "Prayer notification failed") }
                }
                finishPlayback(token, "Athan disabled for ${kind.name}", test, at)
                return
            }
            val challenge = !test && kind == PrayerKind.Fajr && snap.requireChallengeToStop
            showForeground(playback = true, canStop = !challenge)
            // A posted notification or denied notification permission must never
            // prevent the independent alarm audio from starting.
            val started = player.play(snap.athanSelection) { status ->
                scope.launch { finishPlayback(token, status, test, at) }
            }
            if (!started) {
                finishPlayback(token, "FAILED: selected recording and default alarm could not start", test, at)
                return
            }
            playbackStarted = true
            recordPlayback("Audio started at maximum alarm volume — confirm it is audible", test, at)
            if (snap.notifyEachPrayer || challenge) {
                runCatching {
                    notifier.notify(this, kind, intent.getLongExtra(PrayerScheduler.EXTRA_EPOCH_MS, 0), challenge)
                }.onFailure { Timber.e(it, "Athan notification failed; playback continues") }
            }
            scope.launch {
                var reportedVolumeFailure = false
                while (generation == token) {
                    if (player.isPlaying && !player.ensureLoudAlarm() && !reportedVolumeFailure) {
                        reportedVolumeFailure = true
                        recordPlayback("WARNING: Android refused maximum alarm volume; check sound settings", test, at)
                    }
                    delay(1_000)
                }
            }
            // Timed tests stop automatically; real athans complete naturally.
            if (test) {
                scope.launch {
                    delay(20_000)
                    if (generation == token) player.stop()
                }
            }
        } catch (e: Exception) {
            if (e is kotlinx.coroutines.CancellationException) throw e
            Timber.e(e, "Athan foreground playback failed")
            generation++
            player.stop()
            finishPlayback(generation, "FAILED: ${e.javaClass.simpleName}", test, at)
        } finally {
            if (token == generation || !playbackActive) releaseStartupWakeLock()
        }
    }

    private suspend fun finishPlayback(token: Int, status: String, test: Boolean, at: Long) {
        if (token != generation) return
        generation++
        playbackActive = false
        releaseStartupWakeLock()
        val message = if (test && playbackStarted && status in setOf("Stopped", "Completed")) {
            "Test audio started and ${status.lowercase()} — confirm you heard it"
        } else if (test && !playbackStarted && status == "Stopped") {
            "Timed test cancelled before audio started"
        } else status
        playbackStarted = false
        recordPlayback(message, test, at)
        if (reliability) showForeground(playback = false) else {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private suspend fun recordPlayback(status: String, test: Boolean, at: Long) {
        try {
            withTimeout(2_000) { checkpoints.playback(status, test, at) }
        } catch (error: Exception) {
            if (error is kotlinx.coroutines.CancellationException && error !is kotlinx.coroutines.TimeoutCancellationException) throw error
            Timber.e(error, "Athan checkpoint write failed; audio is independent")
        }
    }

    private fun acquireStartupWakeLock() {
        runCatching {
            val lock = startupWakeLock ?: getSystemService<PowerManager>()
                ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "omono:athan-start")
                ?.apply { setReferenceCounted(false) }
            startupWakeLock = lock
            lock?.acquire(30_000)
        }.onFailure { Timber.e(it, "Athan startup wake lock unavailable") }
    }

    private fun releaseStartupWakeLock() {
        runCatching { startupWakeLock?.let { if (it.isHeld) it.release() } }
    }

    private fun showForeground(playback: Boolean, canStop: Boolean = false) {
        val manager = getSystemService<NotificationManager>()
        if (manager?.getNotificationChannel(CHANNEL_ID) == null) {
            manager?.createNotificationChannel(NotificationChannel(CHANNEL_ID, "Prayer alarms", NotificationManager.IMPORTANCE_LOW).apply {
                setSound(null, null)
                setShowBadge(false)
            })
        }
        val launch = packageManager.getLaunchIntentForPackage(packageName)?.let {
            PendingIntent.getActivity(this, 0, it, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(net.omarss.omono.core.notification.R.drawable.ic_notification_small)
            .setContentTitle(if (playback) "Athan alarm sounding" else "Prayer alarms active")
            .setContentText(if (playback) "Playing through the alarm stream at maximum volume" else "Prayer reliability mode")
            .setContentIntent(launch).setOngoing(true).setSilent(true).setOnlyAlertOnce(true)
            .setCategory(if (playback) NotificationCompat.CATEGORY_ALARM else NotificationCompat.CATEGORY_SERVICE)
            .apply {
                if (canStop) {
                    val stop = PendingIntent.getService(this@PrayerKeepAliveService, 1,
                        Intent(this@PrayerKeepAliveService, PrayerKeepAliveService::class.java).setAction(ACTION_STOP),
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                    addAction(0, "Stop athan", stop)
                }
            }.build()
        val type = when {
            playback && Build.VERSION.SDK_INT >= 29 -> ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
            Build.VERSION.SDK_INT >= 34 -> ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            else -> 0
        }
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification, type)
    }

    override fun onDestroy() {
        running = false
        releaseStartupWakeLock()
        playbackActive = false
        generation++
        player.stop()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        // Outside the 7400..7405 prayer notification range.
        const val NOTIFICATION_ID = 7480
        const val CHANNEL_ID = "omono.prayer.keep_alive"
        @Volatile private var running = false
        private const val ACTION_PLAY = "net.omarss.omono.prayer.PLAY"
        private const val ACTION_STOP = "net.omarss.omono.prayer.STOP"
        private const val ACTION_DISABLE_RELIABILITY = "net.omarss.omono.prayer.DISABLE_RELIABILITY"

        fun start(context: Context) {
            runCatching { context.startForegroundService(Intent(context, PrayerKeepAliveService::class.java)) }
                .onFailure { Timber.e(it, "Prayer reliability service start failed") }
        }

        fun stop(context: Context) {
            // Do not stop a currently sounding alarm when reliability mode is disabled.
            if (!running) return
            runCatching {
                context.startService(Intent(context, PrayerKeepAliveService::class.java).setAction(ACTION_DISABLE_RELIABILITY))
            }.onFailure { Timber.e(it, "Disabling prayer reliability mode failed") }
        }

        fun stopPlayback(context: Context) {
            if (!running) return
            runCatching {
                context.startService(Intent(context, PrayerKeepAliveService::class.java).setAction(ACTION_STOP))
            }.onFailure { Timber.e(it, "Stopping athan failed") }
        }

        fun play(context: Context, kind: PrayerKind, at: Long, test: Boolean): Boolean = runCatching {
            context.startForegroundService(Intent(context, PrayerKeepAliveService::class.java).setAction(ACTION_PLAY).apply {
                putExtra(PrayerScheduler.EXTRA_KIND, kind.name)
                putExtra(PrayerScheduler.EXTRA_EPOCH_MS, at)
                putExtra(PrayerScheduler.EXTRA_TEST, test)
            })
        }.onFailure { Timber.e(it, "Athan foreground service could not start") }.isSuccess
    }
}
