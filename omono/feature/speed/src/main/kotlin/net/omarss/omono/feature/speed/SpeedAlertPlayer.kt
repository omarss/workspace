package net.omarss.omono.feature.speed

import android.media.AudioManager
import android.media.ToneGenerator
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
// limit. Uses STREAM_ALARM so the user's alarm volume drives loudness
// (not media or notification) — this means the alert will ride on top
// of music, phone calls, and silent-for-notifications modes, and only
// goes quiet if the alarm volume itself is muted, which is what you'd
// want.
@Singleton
class SpeedAlertPlayer @Inject constructor() {

    // ToneGenerator is native and can fail on some devices (null Audio
    // service, permission issues). Wrap it in runCatching so a broken
    // audio subsystem never crashes the speed feature.
    private val toneGenerator: ToneGenerator? by lazy {
        runCatching { ToneGenerator(AudioManager.STREAM_ALARM, MAX_VOLUME) }
            .onFailure { Timber.w(it, "ToneGenerator init failed") }
            .getOrNull()
    }

    private var lastAlertAtMillis: Long = 0

    fun alert() {
        val tg = toneGenerator ?: return
        val now = System.currentTimeMillis()
        if (now - lastAlertAtMillis < MIN_INTERVAL_MS) return
        lastAlertAtMillis = now
        runCatching {
            // Stop any in-flight tone so rapid crossings replace the
            // previous beep instead of queueing.
            tg.stopTone()
            // TONE_CDMA_ALERT_CALL_GUARD is a distinctive multi-beep
            // sequence; ~1.2 s is long enough to be noticed without
            // fighting with other audio.
            tg.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, TONE_DURATION_MS)
        }.onFailure { Timber.w(it, "ToneGenerator play failed") }
    }

    private companion object {
        const val MAX_VOLUME = 100
        const val MIN_INTERVAL_MS = 3_000L
        const val TONE_DURATION_MS = 1_200
    }
}
