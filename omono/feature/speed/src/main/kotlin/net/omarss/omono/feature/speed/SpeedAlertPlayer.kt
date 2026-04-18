package net.omarss.omono.feature.speed

import android.app.NotificationManager
import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Handler
import android.os.Looper
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Pure decision function for "should we beep right now?" — the transition
// logic is extracted so it can be unit-tested without the Android audio
// stack. Returns true only on a rising edge (not-over → over), so a
// steady over-limit state plays exactly one tone.
internal fun shouldAlertOnCrossing(
    previousOverLimit: Boolean,
    speedKmh: Float,
    limitKmh: Float?,
): Boolean {
    if (limitKmh == null) return false
    val nowOver = speedKmh > limitKmh
    return nowOver && !previousOverLimit
}

// Short, loud alert played when the user crosses the posted speed
// limit. Designed to be audible under as many phone states as
// Android allows an app to bypass:
//
//   1. Rides STREAM_ALARM, so it ignores silent mode / notification
//      mute / media volume / phone-call routing.
//   2. Snapshots the current alarm volume, raises it to the stream
//      max for the duration of the tone, and restores it afterwards —
//      so a user who had alarm volume at 10% still hears the beep
//      at 100%, and never loses their original setting.
//   3. If the user has granted "Do Not Disturb access"
//      (ACCESS_NOTIFICATION_POLICY + a trip to system settings),
//      the player briefly calls setInterruptionFilter(ALL) so the
//      tone plays even in DND modes that normally suppress it.
//      The previous filter is restored afterwards.
//
// The only silencing Android *does not* let us bypass is "Total
// silence" DND mode — that's enforced by the OS and there's no API
// to override it.
@Singleton
class SpeedAlertPlayer @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val audioManager by lazy { context.getSystemService(AudioManager::class.java) }
    private val notificationManager by lazy {
        context.getSystemService(NotificationManager::class.java)
    }

    // ToneGenerator is native and can fail on some devices. Wrap it in
    // runCatching so a broken audio subsystem never crashes the feature.
    private val toneGenerator: ToneGenerator? by lazy {
        runCatching { ToneGenerator(AudioManager.STREAM_ALARM, MAX_VOLUME) }
            .onFailure { Timber.w(it, "ToneGenerator init failed") }
            .getOrNull()
    }

    private val handler = Handler(Looper.getMainLooper())
    private var lastAlertAtMillis: Long = 0

    // Saved state to restore after the tone finishes. Captured ONCE per
    // alert burst so a back-to-back alert doesn't snapshot our own
    // already-raised state as the "original" — the debounce handles the
    // common case but this is a belt-and-braces guard.
    private var savedStreamVolume: Int? = null
    private var savedInterruptionFilter: Int? = null

    private val restoreRunnable = Runnable { restoreState() }

    fun alert() {
        playTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, TONE_DURATION_MS)
    }

    // Looping "put the phone down" tone for the distraction guard.
    // Fires every BEEP_INTERVAL_MS until stopBeeping() is called. Uses
    // a separate code path from playTone because that path is
    // throttled by MIN_INTERVAL_MS — looping beeps intentionally want
    // to fire faster than the post-alert cool-down allows.
    fun startBeeping() {
        val tg = toneGenerator ?: return
        // Cancel any pending post-alert restore so the looper can
        // keep the stream volume raised without it being pulled back
        // mid-beep.
        handler.removeCallbacks(restoreRunnable)
        snapshotAndBypass()
        handler.removeCallbacks(beepRunnable)
        handler.post(beepRunnable)
        Unit // ensure single-expression body type
        // Warm the ToneGenerator — first call after idle can be slow.
        runCatching { tg.stopTone() }
    }

    fun stopBeeping() {
        handler.removeCallbacks(beepRunnable)
        runCatching { toneGenerator?.stopTone() }
        // Schedule restore the same way a one-shot alert would.
        handler.postDelayed(restoreRunnable, RESTORE_MARGIN_MS)
    }

    // Private loop body — posts itself back on the handler after each
    // tone so the cadence is driven by the handler's clock, not by a
    // coroutine scope that might be cancelled out from under us.
    private val beepRunnable = object : Runnable {
        override fun run() {
            val tg = toneGenerator ?: return
            runCatching {
                tg.stopTone()
                tg.startTone(ToneGenerator.TONE_CDMA_ABBR_ALERT, BEEP_TONE_DURATION_MS)
            }.onFailure { Timber.w(it, "beep loop tone failed") }
            handler.postDelayed(this, BEEP_INTERVAL_MS)
        }
    }

    private fun playTone(toneType: Int, durationMs: Int) {
        val tg = toneGenerator ?: return
        val now = System.currentTimeMillis()
        if (now - lastAlertAtMillis < MIN_INTERVAL_MS) return
        lastAlertAtMillis = now

        // Cancel any pending restore from a previous alert — we're about
        // to play again before the restore would have fired.
        handler.removeCallbacks(restoreRunnable)

        snapshotAndBypass()

        runCatching {
            tg.stopTone()
            tg.startTone(toneType, durationMs)
        }.onFailure { Timber.w(it, "ToneGenerator play failed") }

        handler.postDelayed(restoreRunnable, durationMs + RESTORE_MARGIN_MS)
    }

    private fun snapshotAndBypass() {
        val am = audioManager
        if (am != null && savedStreamVolume == null) {
            savedStreamVolume = runCatching { am.getStreamVolume(AudioManager.STREAM_ALARM) }
                .getOrNull()
            runCatching {
                val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
                am.setStreamVolume(AudioManager.STREAM_ALARM, max, 0)
            }.onFailure { Timber.w(it, "setStreamVolume denied") }
        }

        val nm = notificationManager
        if (nm != null && savedInterruptionFilter == null) {
            // isNotificationPolicyAccessGranted returns true only if the
            // user has given us DND access via system settings. Without
            // it, setInterruptionFilter throws SecurityException — we
            // silently skip in that case and rely on STREAM_ALARM for
            // loudness.
            if (nm.isNotificationPolicyAccessGranted) {
                savedInterruptionFilter = runCatching { nm.currentInterruptionFilter }
                    .getOrNull()
                runCatching {
                    nm.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALL)
                }.onFailure { Timber.w(it, "setInterruptionFilter denied") }
            }
        }
    }

    private fun restoreState() {
        val am = audioManager
        savedStreamVolume?.let { volume ->
            runCatching { am?.setStreamVolume(AudioManager.STREAM_ALARM, volume, 0) }
        }
        savedStreamVolume = null

        val nm = notificationManager
        savedInterruptionFilter?.let { filter ->
            runCatching { nm?.setInterruptionFilter(filter) }
        }
        savedInterruptionFilter = null
    }

    private companion object {
        const val MAX_VOLUME = 100
        const val MIN_INTERVAL_MS = 3_000L
        const val TONE_DURATION_MS = 1_200
        const val BEEP_TONE_DURATION_MS = 400
        const val BEEP_INTERVAL_MS = 900L
        const val RESTORE_MARGIN_MS = 300L
    }
}
