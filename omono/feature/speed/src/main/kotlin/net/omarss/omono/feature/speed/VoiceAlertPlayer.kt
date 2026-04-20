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
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
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
//
// Loop orchestration (phone-use distraction) lives in SpeedAlertPlayer
// rather than here — it needs to interleave speech with beep bursts,
// which requires awareness of both audio paths.
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
    @Volatile private var funMode: Boolean = false

    private var tts: TextToSpeech? = null
    private var ttsReady: Boolean = false
    private var savedStreamVolume: Int? = null

    // Map of utterance id → optional caller callback. onDone fires the
    // matching callback and drops the entry. A map (rather than a
    // single field) is paranoia-safe against any race where QUEUE_FLUSH
    // emits the previous utterance's onDone after the new one has
    // registered its callback — the ids are unique per speak call.
    private val pendingCallbacks = ConcurrentHashMap<String, () -> Unit>()
    private val utteranceCounter = AtomicLong(0L)

    init {
        scope.launch {
            combine(
                settings.voiceAlertsEnabled,
                settings.voiceAlertLanguage,
                settings.funMode,
            ) { e, lang, fun_ -> Triple(e, lang, fun_) }.collect { (e, lang, fun_) ->
                enabled = e
                language = lang
                funMode = fun_
            }
        }
    }

    // Speak one utterance. Returns true if TTS accepted the phrase;
    // false if voice alerts are disabled, TTS isn't ready, or the
    // target locale isn't installed — caller falls back to beep.
    //
    // `onDone` (optional) fires on the main handler when the utterance
    // finishes playing. Callers can use it to chain audio — e.g.
    // SpeedAlertPlayer plays a tone *after* the spoken phrase so the
    // driver hears both without them colliding.
    fun speakOnce(phrase: VoiceAlertPhrase, onDone: (() -> Unit)? = null): Boolean {
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
        // Fun mode swaps the canned imperative for a random zinger
        // from the bundled phrase bank. Still honours the user's
        // language selection — Arabic phrases play when the locale
        // resolves to ar, English otherwise.
        val text = if (funMode) {
            when (locale.language) {
                "ar" -> FunPhrases.arabic.random()
                else -> FunPhrases.english.random()
            }
        } else {
            when (locale.language) {
                "ar" -> phrase.arabic
                else -> phrase.english
            }
        }
        raiseStreamVolume()
        val utteranceId = "${phrase.name}-${utteranceCounter.incrementAndGet()}"
        if (onDone != null) pendingCallbacks[utteranceId] = onDone
        val result = runCatching {
            engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
        }.getOrElse {
            Timber.w(it, "VoiceAlertPlayer: speak failed")
            pendingCallbacks.remove(utteranceId)
            return false
        }
        if (result != TextToSpeech.SUCCESS) {
            pendingCallbacks.remove(utteranceId)
            return false
        }
        return true
    }

    // Stop any in-flight speech and restore alarm-stream volume. Called
    // by SpeedAlertPlayer when the beeping/voicing session ends.
    fun stop() {
        runCatching { tts?.stop() }
        pendingCallbacks.clear()
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
                tts?.setOnUtteranceProgressListener(utteranceListener)
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
            VoiceAlertLanguage.Arabic -> Locale.forLanguageTag("ar-SA")
            VoiceAlertLanguage.English -> Locale.ENGLISH
            VoiceAlertLanguage.Auto -> null
        }
        if (explicit != null) return explicit
        val device = Locale.getDefault()
        return if (device.language.equals("ar", ignoreCase = true)) {
            Locale.forLanguageTag("ar-SA")
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

    // Dispatches per-utterance callbacks. Volume restore is the
    // caller's responsibility via stop() — leaving it on here would
    // yo-yo the alarm stream during a voice+beep sequence.
    private val utteranceListener = object : UtteranceProgressListener() {
        override fun onStart(utteranceId: String?) = Unit

        override fun onDone(utteranceId: String?) {
            val cb = utteranceId?.let { pendingCallbacks.remove(it) } ?: return
            handler.post { cb() }
        }

        @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
        override fun onError(utteranceId: String?) {
            val cb = utteranceId?.let { pendingCallbacks.remove(it) } ?: return
            // Still invoke so the caller can fall back to a beep even
            // when TTS hits a mid-utterance error.
            handler.post { cb() }
        }
    }
}
