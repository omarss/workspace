package net.omarss.omono.feature.speed

import android.app.NotificationManager
import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
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
    private val settings: SpeedSettingsRepository,
) {

    private val audioManager by lazy { context.getSystemService(AudioManager::class.java) }
    private val vibrator: Vibrator? by lazy {
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = context.getSystemService(VibratorManager::class.java)
                vm?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                context.getSystemService(Vibrator::class.java)
            }
        }.onFailure { Timber.w(it, "Vibrator init failed") }.getOrNull()
    }

    // Settings scope — subscribes to alertMode so alert() / loop paths
    // read the current rendering choice without re-querying DataStore
    // on every tick.
    private val settingsScope = CoroutineScope(Dispatchers.Main.immediate + SupervisorJob())
    @Volatile private var alertMode: AlertMode = AlertMode.Default

    init {
        settings.alertMode
            .onEach { alertMode = it }
            .launchIn(settingsScope)
    }
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
        when (alertMode) {
            AlertMode.VibrateOnly -> {
                // Haptic-only — a two-pulse pattern distinct from any
                // notification vibration the phone might already be
                // producing. Accompanying beep/voice are suppressed.
                vibrate(SHORT_ALERT_PATTERN)
            }
            AlertMode.BeepOnly -> {
                // Tone without voice. Vibration rides alongside so
                // the haptic cue still lands — the removed layer is
                // the spoken phrase, not the tactile feedback.
                vibrate(SHORT_ALERT_PATTERN)
                playTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, TONE_DURATION_MS)
            }
            AlertMode.Default -> {
                val spoke = voiceAlertPlayer.speakOnce(phrase) {
                    playTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, TONE_DURATION_MS)
                }
                if (!spoke) {
                    // Voice disabled or TTS unavailable — beep
                    // immediately so the driver isn't left guessing.
                    playTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, TONE_DURATION_MS)
                }
                // Haptic always accompanies the audible alert in
                // Default mode — belt-and-braces for a driver with
                // the radio up.
                vibrate(SHORT_ALERT_PATTERN)
            }
        }
    }

    // Fire-and-forget vibration. Pattern is `[delay, on, off, on, ...]`
    // millis. We drive every "on" slot at max amplitude (255) so the
    // haptic is unmissable on a driver's leg through a pocket or
    // strap — the previous DEFAULT_AMPLITUDE path rendered on some
    // handsets as a barely-there buzz. Off slots get amplitude 0 so
    // the phone is silent between pulses instead of faintly humming.
    private fun vibrate(pattern: LongArray) {
        val v = vibrator ?: return
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val amplitudes = IntArray(pattern.size) { idx ->
                    // pattern layout: [delay, on, off, on, off, ...]
                    // index 0 is the leading delay (always silent);
                    // odd indexes are "on" slots; even > 0 are "off".
                    // 255 is the createWaveform max (scale 1..255).
                    if (idx == 0 || idx % 2 == 0) 0 else MAX_AMPLITUDE
                }
                // Use the explicit-amplitude overload so devices that
                // support variable haptics render our "on" slots at
                // full strength instead of their engine default.
                v.vibrate(VibrationEffect.createWaveform(pattern, amplitudes, -1))
            } else {
                @Suppress("DEPRECATION")
                v.vibrate(pattern, -1)
            }
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
        if (alertMode == AlertMode.VibrateOnly) {
            // Vibrate-only loop — runs a repeating pulse on the
            // handler rather than the tone/voice runnables. Stays
            // clear of the audio stream entirely.
            handler.removeCallbacks(vibrateLoopRunnable)
            handler.post(vibrateLoopRunnable)
            return
        }
        // Reset any lingering one-shot restore — we're holding the
        // stream volume raised for the duration of the loop.
        handler.removeCallbacks(restoreRunnable)
        snapshotAndBypass()
        // currentLoopPhrase doubles as the "is the loop running"
        // sentinel — stopBeeping() clears it to break the runnable —
        // so set it even in BeepOnly mode. The loop body reads
        // alertMode separately to decide whether to actually speak.
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
        handler.removeCallbacks(vibrateLoopRunnable)
        runCatching { toneGenerator?.stopTone() }
        runCatching { vibrator?.cancel() }
        // Schedule restore the same way a one-shot alert would.
        handler.postDelayed(restoreRunnable, RESTORE_MARGIN_MS)
    }

    // Vibrate-only distraction loop — pulses every ~1.5 s while
    // `startBeeping` is active. Cadence matches the audible loop
    // interval so the user feels a steady nag rather than a one-off.
    private val vibrateLoopRunnable = object : Runnable {
        override fun run() {
            vibrate(LOOP_VIBRATE_PATTERN)
            handler.postDelayed(this, LOOP_INTERVAL_MS)
        }
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
            // In BeepOnly mode the voice layer is suppressed — the
            // loop still plays tones + vibrations, just without TTS.
            val shouldSpeak = alertMode == AlertMode.Default &&
                now - lastSpokenAtMillis >= VOICE_INTERVAL_MS
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

        // createWaveform amplitudes run 1..255; anything lower feels
        // weak on strap or in a pocket, so we always drive at the top.
        const val MAX_AMPLITUDE = 255
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

        // Vibrate patterns. Waveform is `[delay, on, off, on, …]` ms.
        // The one-shot alert is two quick 200 ms pulses (feels like
        // a double-tap); the loop variant is one punchier 400 ms
        // pulse per tick so the wrist/pocket feels the same rhythm
        // as the audible beep loop.
        val SHORT_ALERT_PATTERN: LongArray = longArrayOf(0L, 200L, 120L, 200L)
        val LOOP_VIBRATE_PATTERN: LongArray = longArrayOf(0L, 400L)
    }
}
