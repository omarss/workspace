package net.omarss.omono.ui.docs

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.omarss.omono.feature.docs.Doc
import net.omarss.omono.feature.docs.DocSubject
import net.omarss.omono.feature.docs.DocSummary
import net.omarss.omono.feature.docs.DocsRepository
import net.omarss.omono.feature.docs.DocsTtsPlayer
import net.omarss.omono.feature.docs.MarkdownBlock
import net.omarss.omono.feature.docs.markdownToUtterances
import net.omarss.omono.feature.docs.parseMarkdownBlocks
import timber.log.Timber
import javax.inject.Inject

// Docs screen state machine — three levels that the UI maps onto a
// single scaffolded column.
//
//   Subjects ─(tap)─▶ Docs ─(tap)─▶ Reader
//       ▲               │              │
//       └─── back ──────┴──── back ────┘
//
// The TTS player reports its own state; we fan it into `TtsState` so
// the screen has one flow to render the playback pill from.
@HiltViewModel
class DocsViewModel @Inject constructor(
    private val repository: DocsRepository,
    private val tts: DocsTtsPlayer,
) : ViewModel() {

    private val _state = MutableStateFlow(
        DocsUiState(configured = repository.isConfigured),
    )
    val state: StateFlow<DocsUiState> = _state.asStateFlow()

    val ttsState: StateFlow<DocsTtsPlayer.State> = tts.state
        .stateIn(viewModelScope, SharingStarted.Eagerly, DocsTtsPlayer.State.Idle)

    val ttsIndex: StateFlow<Int?> = tts.currentIndex
        .stateIn(viewModelScope, SharingStarted.Eagerly, null)

    private var docsJob: Job? = null
    private var readerJob: Job? = null

    init {
        if (repository.isConfigured) refreshSubjects()
    }

    fun refreshSubjects() {
        if (!repository.isConfigured) return
        viewModelScope.launch {
            _state.update { it.copy(loadingSubjects = true, error = null) }
            val fetched = runCatching { repository.subjects() }
                .onFailure { Timber.w(it, "docs subjects load failed") }
                .getOrNull()
                .orEmpty()
            _state.update {
                it.copy(
                    loadingSubjects = false,
                    subjects = fetched,
                    // If subjects load empties even though we're
                    // configured, surface the generic "backend hasn't
                    // shipped yet" banner. It's not strictly wrong —
                    // 43 subjects is constant on the mcqs backend.
                    subjectsError = if (fetched.isEmpty()) {
                        "Docs service isn't reachable. Check back later."
                    } else null,
                )
            }
        }
    }

    fun openSubject(subject: DocSubject) {
        _state.update {
            it.copy(
                view = DocsView.Docs,
                selectedSubject = subject,
                docs = emptyList(),
                docsError = null,
            )
        }
        docsJob?.cancel()
        docsJob = viewModelScope.launch {
            _state.update { it.copy(loadingDocs = true) }
            val fetched = runCatching { repository.list(subject.slug) }
                .onFailure { Timber.w(it, "docs list failed for %s", subject.slug) }
                .getOrNull()
                .orEmpty()
            _state.update {
                it.copy(
                    loadingDocs = false,
                    docs = fetched,
                    docsError = if (fetched.isEmpty()) {
                        "No docs available for ${subject.title} yet."
                    } else null,
                )
            }
        }
    }

    fun openDoc(summary: DocSummary) {
        _state.update {
            it.copy(
                view = DocsView.Reader,
                selectedDocSummary = summary,
                reader = null,
                readerError = null,
            )
        }
        readerJob?.cancel()
        readerJob = viewModelScope.launch {
            _state.update { it.copy(loadingReader = true) }
            val doc = runCatching { repository.fetch(summary.subject, summary.id) }
                .onFailure { Timber.w(it, "docs fetch failed %s/%s", summary.subject, summary.id) }
                .getOrNull()
            if (doc == null) {
                _state.update {
                    it.copy(
                        loadingReader = false,
                        readerError = "Couldn't load this doc. Tap retry.",
                    )
                }
                return@launch
            }
            val blocks = parseMarkdownBlocks(doc.markdown)
            val utterances = markdownToUtterances(doc.markdown)
            _state.update {
                it.copy(
                    loadingReader = false,
                    reader = ReaderPayload(
                        doc = doc,
                        blocks = blocks,
                        utterances = utterances,
                    ),
                )
            }
        }
    }

    fun backToDocs() {
        stopTts()
        _state.update {
            it.copy(view = DocsView.Docs, selectedDocSummary = null, reader = null)
        }
    }

    fun backToSubjects() {
        stopTts()
        _state.update {
            it.copy(
                view = DocsView.Subjects,
                selectedSubject = null,
                docs = emptyList(),
            )
        }
    }

    fun playReader() {
        val utterances = _state.value.reader?.utterances.orEmpty()
        if (utterances.isEmpty()) return
        tts.play(utterances, fromIndex = 0)
    }

    fun pauseReader() = tts.pause()
    fun resumeReader() = tts.resume()
    fun stopTts() = tts.stop()
    fun skipForward() = tts.skipForward()
    fun skipBackward() = tts.skipBackward()

    override fun onCleared() {
        super.onCleared()
        tts.stop()
    }
}

enum class DocsView { Subjects, Docs, Reader }

data class ReaderPayload(
    val doc: Doc,
    val blocks: List<MarkdownBlock>,
    val utterances: List<String>,
)

data class DocsUiState(
    val configured: Boolean = true,
    val view: DocsView = DocsView.Subjects,
    val loadingSubjects: Boolean = false,
    val loadingDocs: Boolean = false,
    val loadingReader: Boolean = false,
    val subjects: List<DocSubject> = emptyList(),
    val subjectsError: String? = null,
    val selectedSubject: DocSubject? = null,
    val docs: List<DocSummary> = emptyList(),
    val docsError: String? = null,
    val selectedDocSummary: DocSummary? = null,
    val reader: ReaderPayload? = null,
    val readerError: String? = null,
    val error: String? = null,
)
