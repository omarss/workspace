package net.omarss.omono.ui.docs

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.omarss.omono.feature.docs.Doc
import net.omarss.omono.feature.docs.DocSubject
import net.omarss.omono.feature.docs.DocSummary
import net.omarss.omono.feature.docs.DocsRepository
import net.omarss.omono.feature.docs.DocsTtsPlayer
import net.omarss.omono.feature.docs.MarkdownBlock
import net.omarss.omono.feature.docs.Utterance
import net.omarss.omono.feature.docs.markdownToUtterances
import net.omarss.omono.feature.docs.parseMarkdownBlocks
import net.omarss.omono.settings.AppSettingsRepository
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
    private val appSettings: AppSettingsRepository,
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
        // Mirror the persisted voice preference into the player so a
        // setting flip takes effect immediately on the currently-open
        // reader session (applied to the next `play()` call).
        viewModelScope.launch {
            appSettings.docsTtsVoiceName.collect { tts.setPreferredVoiceName(it) }
        }
        // Auto-advance: when the reader finishes a doc naturally, if
        // the user has the setting on and there's a next doc in the
        // current subject, open it and start reading.
        viewModelScope.launch {
            tts.finished.collect { onReaderFinished() }
        }
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
                docsSearch = "",
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
        // Cancel any in-flight reader load before state-swapping so
        // the old fetch can't clobber the new view with a stale
        // ReaderPayload when it completes after the tap.
        readerJob?.cancel()
        _state.update {
            it.copy(
                view = DocsView.Reader,
                selectedDocSummary = summary,
                reader = null,
                readerError = null,
            )
        }
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
                docsSearch = "",
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

    // Search — pure client-side substring match, case-insensitive.
    // Cheap because even the largest subject tops out around 1.6k
    // docs, and we filter off the already-fetched `state.docs`.
    fun setSubjectsSearch(query: String) {
        _state.update { it.copy(subjectsSearch = query) }
    }

    fun setDocsSearch(query: String) {
        _state.update { it.copy(docsSearch = query) }
    }

    // Called when the reader's TTS player emits its natural-finish
    // signal. Chains to the next DocSummary when auto-advance is on
    // and the current doc isn't the last in the subject; otherwise
    // leaves the reader idle on the finished doc.
    private suspend fun onReaderFinished() {
        // Read the latest persisted setting without suspending on
        // the full flow — the setting is flipped from the Settings
        // screen, so first() reads the current DataStore value.
        val enabled = runCatching { appSettings.docsAutoAdvance.first() }
            .getOrDefault(true)
        if (!enabled) return

        val snapshot = _state.value
        val currentId = snapshot.selectedDocSummary?.id ?: return
        val docs = snapshot.docs
        val idx = docs.indexOfFirst { it.id == currentId }
        if (idx < 0 || idx + 1 >= docs.size) return
        val next = docs[idx + 1]
        openDoc(next)
        // openDoc launches a job that hydrates ReaderPayload; wait
        // for that to land before pressing play.
        readerJob?.join()
        playReader()
    }

    override fun onCleared() {
        super.onCleared()
        tts.stop()
    }
}

enum class DocsView { Subjects, Docs, Reader }

data class ReaderPayload(
    val doc: Doc,
    val blocks: List<MarkdownBlock>,
    val utterances: List<Utterance>,
)

data class DocsUiState(
    val configured: Boolean = true,
    val view: DocsView = DocsView.Subjects,
    val loadingSubjects: Boolean = false,
    val loadingDocs: Boolean = false,
    val loadingReader: Boolean = false,
    val subjects: List<DocSubject> = emptyList(),
    val subjectsError: String? = null,
    val subjectsSearch: String = "",
    val selectedSubject: DocSubject? = null,
    val docs: List<DocSummary> = emptyList(),
    val docsError: String? = null,
    val docsSearch: String = "",
    val selectedDocSummary: DocSummary? = null,
    val reader: ReaderPayload? = null,
    val readerError: String? = null,
    val error: String? = null,
) {
    // Filtered subjects / docs derived on the fly from the search
    // strings. Kept as properties so the composable reads a single
    // source of truth rather than filtering in-render.
    val filteredSubjects: List<DocSubject>
        get() = if (subjectsSearch.isBlank()) subjects
        else subjects.filter {
            it.title.contains(subjectsSearch, ignoreCase = true) ||
                it.slug.contains(subjectsSearch, ignoreCase = true)
        }

    val filteredDocs: List<DocSummary>
        get() = if (docsSearch.isBlank()) docs
        else docs.filter {
            it.title.contains(docsSearch, ignoreCase = true) ||
                (it.path?.contains(docsSearch, ignoreCase = true) == true)
        }
}
