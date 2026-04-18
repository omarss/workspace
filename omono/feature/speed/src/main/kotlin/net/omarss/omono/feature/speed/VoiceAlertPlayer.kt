package net.omarss.omono.feature.speed

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import timber.log.Timber
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

// Speaks short driver-facing phrases instead of beeping. Routes audio
// through USAGE_ALARM (same stream as SpeedAlertPlayer's ToneGenerator)
// so silent mode / media-volume mute don't swallow the voice. Matches
// the existing snapshot-and-raise-stream-volume pattern so a user with
// alarm volume at 10% still hears the voice at 100%.
//
// Unlike the beep path, we don't touch the DND interruption filter —
// USAGE_ALARM already bypasses normal DND, and touching the filter
// here would race with the beep path's snapshot. DND-only users can
// leave voice alerts off and keep the existing beep behaviour.
//
// TTS init is lazy + once: the engine isn't cheap to construct so we
// kick it off on the first speak call and hold the handle for the
// lifetime of the process. Init failure falls through to the caller
// (returns false) so SpeedAlertPlayer can beep instead.
@Singleton
class VoiceAlertPlayer @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val settings: SpeedSettingsRepository,
) {

    private val audioManager by lazy { context.getSystemService(AudioManager::class.java) }
    private val handler = Handler(Looper.getMainLooper())

    // Main.immediate so setting-flow updates land on the same thread
    // the speak methods run on — no extra synchronisation needed.
    private val scope = CoroutineScope(Dispatchers.Main.immediate + SupervisorJob())

    @Volatile private var enabled: Boolean = false
    @Volatile private var language: VoiceAlertLanguage = VoiceAlertLanguage.Auto

    private var tts: TextToSpeech? = null
    private var ttsReady: Boolean = false
    private var savedStreamVolume: Int? = null

    private var loopRunnable: Runnable? = null

    init {
        scope.launch {
            combine(
                settings.voiceAlertsEnabled,
                settings.voiceAlertLanguage,
            ) { e, lang -> e to lang }.collect { (e, lang) ->
                enabled = e
                language = lang
            }
        }
    }

    // Speak one utterance. Returns true if TTS accepted the phrase;
    // false if voice alerts are disabled, TTS isn't ready, or the
    // target locale isn't installed — caller falls back to beep.
    fun speakOnce(phrase: VoiceAlertPhrase): Boolean {
        if (!enabled) return false
        val engine = ensureTts() ?: return false
        val locale = resolveLocale() ?: return false
        val availability = engine.setLanguage(locale)
        if (availability == TextToSpeech.LANG_MISSING_DATA ||
            availability == TextToSpeech.LANG_NOT_SUPPORTED
        ) {
            Timber.w(
                "VoiceAlertPlayer: locale %s unavailable (result=%d)",
                locale, availability,
            )
            return false
        }
        val text = when (locale.language) {
            "ar" -> phrase.arabic
            else -> phrase.english
        }
        raiseStreamVolume()
        val result = runCatching {
            engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, phrase.name)
        }.getOrElse {
            Timber.w(it, "VoiceAlertPlayer: speak failed")
            return false
        }
        return result == TextToSpeech.SUCCESS
    }

    fun startLoop(phrase: VoiceAlertPhrase): Boolean {
        stopLoop()
        if (!speakOnce(phrase)) return false
        loopRunnable = object : Runnable {
            override fun run() {
                speakOnce(phrase)
                handler.postDelayed(this, LOOP_INTERVAL_MS)
            }
        }.also { handler.postDelayed(it, LOOP_INTERVAL_MS) }
        return true
    }

    fun stopLoop() {
        loopRunnable?.let { handler.removeCallbacks(it) }
        loopRunnable = null
        runCatching { tts?.stop() }
        restoreStreamVolume()
    }

    private fun ensureTts(): TextToSpeech? {
        if (ttsReady) return tts
        if (tts != null) return null
        tts = TextToSpeech(context.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build(),
                )
                tts?.setOnUtteranceProgressListener(restoreOnDone)
                ttsReady = true
                Timber.i("VoiceAlertPlayer: TTS ready")
            } else {
                Timber.w("VoiceAlertPlayer: TTS init failed (status=%d)", status)
            }
        }
        // First speak call after init returns null — the next call will
        // pick it up once onInit fires.
        return null
    }

    private fun resolveLocale(): Locale? {
        val explicit = when (language) {
            VoiceAlertLanguage.Arabic -> Locale("ar", "SA")
            VoiceAlertLanguage.English -> Locale.ENGLISH
            VoiceAlertLanguage.Auto -> null
        }
        if (explicit != null) return explicit
        val device = Locale.getDefault()
        return if (device.language.equals("ar", ignoreCase = true)) {
            Locale("ar", "SA")
        } else {
            Locale.ENGLISH
        }
    }

    private fun raiseStreamVolume() {
        val am = audioManager ?: return
        if (savedStreamVolume != null) return // already raised
        savedStreamVolume = runCatching {
            am.getStreamVolume(AudioManager.STREAM_ALARM)
        }.getOrNull()
        runCatching {
            val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            am.setStreamVolume(AudioManager.STREAM_ALARM, max, 0)
        }.onFailure { Timber.w(it, "VoiceAlertPlayer: setStreamVolume denied") }
    }

    private fun restoreStreamVolume() {
        val am = audioManager
        savedStreamVolume?.let { volume ->
            runCatching { am?.setStreamVolume(AudioManager.STREAM_ALARM, volume, 0) }
        }
        savedStreamVolume = null
    }

    private val restoreOnDone = object : UtteranceProgressListener() {
        override fun onStart(utteranceId: String?) = Unit
        override fun onDone(utteranceId: String?) {
            // Only restore when no loop is active — a running loop will
            // speak again immediately and we want the volume held.
            if (loopRunnable == null) {
                handler.post { restoreStreamVolume() }
            }
        }
        @Deprecated("Deprecated in Java")
        override fun onError(utteranceId: String?) {
            handler.post { restoreStreamVolume() }
        }
    }

    private companion object {
        // Pause between loop utterances. Long enough that back-to-back
        // speech doesn't blur into one string; short enough that a
        // distracted driver hears the phrase again within a glance.
        const val LOOP_INTERVAL_MS = 4_000L
    }
}
