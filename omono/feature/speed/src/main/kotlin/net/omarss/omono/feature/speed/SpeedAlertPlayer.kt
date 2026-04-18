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
    private val voiceAlertPlayer: VoiceAlertPlayer,
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

    // One-shot alert. Always plays the tone; if voice alerts are on,
    // speaks the phrase first and chains the tone onto the utterance
    // onDone callback so the driver hears "Slow down" immediately
    // followed by a distinct beep. A voice-only alert is easy to
    // miss in traffic — the beep makes the pair impossible to ignore.
    //
    // Silently no-ops while the user is on a phone call — stepping on
    // the call audio would cause more confusion than the limit breach.
    fun alert(phrase: VoiceAlertPhrase = VoiceAlertPhrase.OVER_LIMIT) {
        if (isInCall()) return
        val spoke = voiceAlertPlayer.speakOnce(phrase) {
            playTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, TONE_DURATION_MS)
        }
        if (!spoke) {
            // Voice disabled or TTS unavailable — beep immediately so
            // the driver isn't left guessing.
            playTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, TONE_DURATION_MS)
        }
    }

    private fun isInCall(): Boolean {
        val mode = audioManager?.mode ?: return false
        return mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_IN_COMMUNICATION
    }

    // Looping "put the phone down" alert for the distraction guard.
    // Each tick fires a beep burst; TTS is throttled to at most once
    // per VOICE_INTERVAL_MS (1 min) so the driver hears the phrase on
    // first offence but isn't drowned in it, while the beep keeps
    // firing steadily so they stay nagged. Falls back to pure-beep
    // when voice isn't available.
    fun startBeeping(phrase: VoiceAlertPhrase = VoiceAlertPhrase.PHONE_USE) {
        // Reset any lingering one-shot restore — we're holding the
        // stream volume raised for the duration of the loop.
        handler.removeCallbacks(restoreRunnable)
        snapshotAndBypass()
        currentLoopPhrase = phrase
        // First tick always speaks so the user hears the phrase the
        // moment they start being distracted.
        lastSpokenAtMillis = 0L
        handler.removeCallbacks(loopRunnable)
        handler.post(loopRunnable)
    }

    fun stopBeeping() {
        currentLoopPhrase = null
        voiceAlertPlayer.stop()
        handler.removeCallbacks(loopRunnable)
        runCatching { toneGenerator?.stopTone() }
        // Schedule restore the same way a one-shot alert would.
        handler.postDelayed(restoreRunnable, RESTORE_MARGIN_MS)
    }

    // Which phrase (if any) the loop is currently cycling. Null means
    // stopBeeping has been called; the runnable bails on the next tick.
    @Volatile private var currentLoopPhrase: VoiceAlertPhrase? = null

    // Last-spoken timestamp for the TTS throttle. Reset on each
    // startBeeping so the first tick of every new offence speaks.
    @Volatile private var lastSpokenAtMillis: Long = 0L

    // Loop body. Every tick plays a beep burst; TTS piggybacks only
    // when the throttle window has elapsed. Driven by the handler's
    // clock so a cancelled coroutine scope upstream can't leave the
    // loop half-running.
    private val loopRunnable = object : Runnable {
        override fun run() {
            val phrase = currentLoopPhrase ?: return
            val now = System.currentTimeMillis()
            val shouldSpeak = now - lastSpokenAtMillis >= VOICE_INTERVAL_MS
            var spoke = false
            if (shouldSpeak) {
                spoke = voiceAlertPlayer.speakOnce(phrase) {
                    // Speech done — beep now so voice + beep land as
                    // a pair. Wrapped in a phrase check so a late
                    // onDone arriving after stopBeeping doesn't fire
                    // a stray tone.
                    if (currentLoopPhrase != null) playBeepBurst()
                }
                if (spoke) lastSpokenAtMillis = now
            }
            if (!spoke) {
                // No speech this tick — just beep. Keeps the driver
                // annoyed between announcement windows.
                playBeepBurst()
            }
            handler.postDelayed(this, LOOP_INTERVAL_MS)
        }
    }

    private fun playBeepBurst() {
        val tg = toneGenerator ?: return
        runCatching {
            tg.stopTone()
            tg.startTone(ToneGenerator.TONE_CDMA_ABBR_ALERT, BEEP_TONE_DURATION_MS)
        }.onFailure { Timber.w(it, "beep burst tone failed") }
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
        const val RESTORE_MARGIN_MS = 300L

        // Beep cadence for the phone-use loop. Short enough to
        // actually annoy the driver; long enough to let each burst
        // register as a discrete beep rather than a continuous tone.
        const val LOOP_INTERVAL_MS = 3_000L

        // Minimum gap between spoken TTS phrases inside the loop.
        // The driver hears "Eyes on the road" once per offence window
        // rather than every cycle — repeating words become background
        // noise; repeating beeps do not.
        const val VOICE_INTERVAL_MS = 60_000L
    }
}
