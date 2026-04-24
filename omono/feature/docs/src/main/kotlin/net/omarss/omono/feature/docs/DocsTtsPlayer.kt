package net.omarss.omono.feature.docs

import android.content.Context
import android.media.AudioAttributes
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import timber.log.Timber
import java.util.Locale
import java.util.concurrent.atomic.AtomicLong
import javax.inject.Inject
import javax.inject.Singleton

// Text-to-speech reader for the docs tab. Separate instance from the
// speed feature's `VoiceAlertPlayer` because:
//   * docs are media content — route through USAGE_MEDIA / STREAM_MUSIC
//     so the reader respects the user's media volume instead of the
//     alarm volume the speed alert hijacks.
//   * docs are long-form — we need play / pause / resume / skip
//     controls that the one-shot alert path doesn't model.
//   * the two paths must not share init state — if the user is driving
//     while a doc is mid-read, the alert path still needs to beep
//     without waiting for the reader to stop.
//
// Engine init is lazy + once. The first `play()` call constructs the
// engine; subsequent calls reuse it. `release()` is called by the
// ViewModel in `onCleared` to reclaim native resources.
@Singleton
class DocsTtsPlayer @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    enum class State { Idle, Speaking, Paused, Unavailable }

    private val _state = MutableStateFlow(State.Idle)
    val state: StateFlow<State> = _state.asStateFlow()

    // Index into the *current* utterance list that the TTS engine is
    // currently on. `null` when nothing is queued. The ViewModel
    // mirrors this into its UI state so the reader can highlight the
    // active block.
    private val _currentIndex = MutableStateFlow<Int?>(null)
    val currentIndex: StateFlow<Int?> = _currentIndex.asStateFlow()

    private val handler = Handler(Looper.getMainLooper())
    private var tts: TextToSpeech? = null
    private var engineReady: Boolean = false

    @Volatile private var utterances: List<String> = emptyList()
    @Volatile private var cursor: Int = 0
    @Volatile private var rate: Float = 1.0f

    private val utteranceCounter = AtomicLong(0L)

    // Start speaking a list of utterances, optionally from an offset
    // other than the start. Returns false only when the engine is
    // unavailable on this device — callers can use that to fall back
    // to a muted UI instead of showing phantom controls.
    fun play(utterances: List<String>, fromIndex: Int = 0): Boolean {
        if (utterances.isEmpty()) return false
        this.utterances = utterances
        this.cursor = fromIndex.coerceIn(0, utterances.lastIndex)
        ensureEngine {
            if (!engineReady) {
                _state.value = State.Unavailable
                return@ensureEngine
            }
            stopInternal()
            _state.value = State.Speaking
            speakFromCursor()
        }
        return true
    }

    fun pause() {
        val engine = tts ?: return
        if (_state.value != State.Speaking) return
        runCatching { engine.stop() }
        _state.value = State.Paused
    }

    fun resume() {
        if (_state.value != State.Paused) return
        if (utterances.isEmpty()) return
        _state.value = State.Speaking
        speakFromCursor()
    }

    fun stop() {
        stopInternal()
        _state.value = State.Idle
        _currentIndex.value = null
    }

    fun skipForward() {
        if (utterances.isEmpty()) return
        val next = (cursor + 1).coerceAtMost(utterances.lastIndex)
        if (next == cursor && _state.value == State.Speaking) {
            // Already on the last utterance — treat forward skip as
            // "stop after this one finishes" by flushing the queue.
            stop()
            return
        }
        cursor = next
        if (_state.value == State.Speaking) {
            runCatching { tts?.stop() }
            speakFromCursor()
        } else {
            _currentIndex.value = cursor
        }
    }

    fun skipBackward() {
        if (utterances.isEmpty()) return
        cursor = (cursor - 1).coerceAtLeast(0)
        if (_state.value == State.Speaking) {
            runCatching { tts?.stop() }
            speakFromCursor()
        } else {
            _currentIndex.value = cursor
        }
    }

    // Playback speed multiplier (1.0 = default). Clamped to the engine's
    // sensible range — 0.5–2.0 covers anyone who isn't torturing
    // themselves.
    fun setRate(newRate: Float) {
        rate = newRate.coerceIn(0.5f, 2.0f)
        runCatching { tts?.setSpeechRate(rate) }
    }

    fun release() {
        stopInternal()
        runCatching { tts?.shutdown() }
        tts = null
        engineReady = false
        _state.value = State.Idle
        _currentIndex.value = null
    }

    // ------------------------------------------------------------------

    private fun ensureEngine(afterInit: () -> Unit) {
        val existing = tts
        if (existing != null && engineReady) {
            afterInit()
            return
        }
        if (existing != null) {
            // Init already in flight — stash the callback on the
            // handler so it runs once ready. For simplicity we just
            // drop the old listener and let the first init call
            // complete; callers invoke afterInit again next press.
            return
        }
        tts = TextToSpeech(context.applicationContext) { status ->
            handler.post {
                engineReady = status == TextToSpeech.SUCCESS
                if (engineReady) {
                    val engine = tts ?: return@post
                    engine.setAudioAttributes(
                        AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                            .build(),
                    )
                    // Default to the device's current locale. Fall
                    // through silently if it isn't supported — the
                    // engine's built-in fallback will pick the best
                    // available voice.
                    runCatching { engine.language = Locale.getDefault() }
                    engine.setSpeechRate(rate)
                    engine.setOnUtteranceProgressListener(progressListener)
                } else {
                    Timber.w("DocsTtsPlayer: TTS init failed (status=%d)", status)
                }
                afterInit()
            }
        }
    }

    private val progressListener = object : UtteranceProgressListener() {
        override fun onStart(utteranceId: String?) {
            val idx = utteranceId?.toIntOrNull() ?: return
            handler.post { _currentIndex.value = idx }
        }

        override fun onDone(utteranceId: String?) {
            handler.post {
                val idx = utteranceId?.toIntOrNull() ?: return@post
                // Only advance if this callback matches the current
                // cursor — otherwise it's a stale utterance from a
                // previous queue that landed after stop().
                if (_state.value != State.Speaking) return@post
                if (idx != cursor) return@post
                val next = idx + 1
                if (next > utterances.lastIndex) {
                    _state.value = State.Idle
                    _currentIndex.value = null
                    utterances = emptyList()
                    cursor = 0
                } else {
                    cursor = next
                    speakFromCursor()
                }
            }
        }

        @Deprecated("Deprecated in API 21, still called on older engines")
        override fun onError(utteranceId: String?) {
            handler.post { Timber.w("DocsTtsPlayer: utterance error on %s", utteranceId) }
        }

        override fun onError(utteranceId: String?, errorCode: Int) {
            handler.post {
                Timber.w(
                    "DocsTtsPlayer: utterance error on %s, code=%d",
                    utteranceId, errorCode,
                )
            }
        }
    }

    private fun speakFromCursor() {
        val engine = tts ?: return
        if (!engineReady) return
        val text = utterances.getOrNull(cursor) ?: return
        val utteranceId = cursor.toString()
        _currentIndex.value = cursor
        // Use QUEUE_FLUSH so a mid-sentence skip replaces the current
        // utterance immediately rather than stacking a second one
        // behind it.
        runCatching {
            engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
        }.onFailure { Timber.w(it, "DocsTtsPlayer: speak failed") }
    }

    private fun stopInternal() {
        runCatching { tts?.stop() }
    }
}
