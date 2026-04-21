package net.omarss.omono.ui.quiz

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import net.omarss.omono.feature.quiz.McqRepository
import net.omarss.omono.feature.quiz.Question
import net.omarss.omono.feature.quiz.QuestionType
import net.omarss.omono.feature.quiz.Subject
import net.omarss.omono.feature.quiz.Topic
import timber.log.Timber
import javax.inject.Inject

// Quiz screen state machine.
//
//   Setup  ── Start ──▶  Playing ── Reveal ─▶ Review ── Next ─▶ Playing
//     ▲                                                     │
//     └───────────────── Back to setup / Finish ────────────┘
//                                        ▲
//                                        └── Done ─▶ Summary
//
// Every state is captured in a single `QuizUiState` so the composable
// just renders one shape. The ViewModel exposes narrow commands
// (start, pickOption, next, restart) and does all the async work.
@HiltViewModel
class QuizViewModel @Inject constructor(
    private val repository: McqRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(QuizUiState(configured = repository.isConfigured))
    val uiState: StateFlow<QuizUiState> = _uiState.asStateFlow()

    init {
        refreshSubjects()
    }

    fun refreshSubjects() {
        if (!repository.isConfigured) return
        viewModelScope.launch {
            _uiState.update { it.copy(loadingSubjects = true, error = null) }
            val fetched = runCatching { repository.subjects() }
                .onFailure { Timber.w(it, "quiz subjects load failed") }
                .getOrNull()
                .orEmpty()
            _uiState.update { it.copy(loadingSubjects = false, subjects = fetched) }
        }
    }

    fun toggleSubject(slug: String) {
        _uiState.update { state ->
            val current = state.selectedSubjects
            val next = if (slug in current) current - slug else current + slug
            // Keep the user's topic picks across subject changes —
            // the backend's `topic=` filter works cross-subject, so
            // a chosen topic stays meaningful even when the subject
            // set shifts underneath it. The topics chip list
            // refreshes via refreshTopics(), but selected slugs are
            // preserved (slugs the new subjects don't tag just
            // disappear from the row but still apply to the query).
            state.copy(selectedSubjects = next)
        }
        refreshTopics()
    }

    fun clearSubjects() {
        _uiState.update {
            it.copy(
                selectedSubjects = emptySet(),
                selectedTopics = emptySet(),
                topics = emptyList(),
            )
        }
    }

    private fun refreshTopics() {
        val subjects = _uiState.value.selectedSubjects
        if (subjects.isEmpty()) return
        viewModelScope.launch {
            _uiState.update { it.copy(loadingTopics = true) }
            // Topics endpoint is single-subject only, so when the
            // user picks multiple subjects we fan-out in sequence
            // and merge. Each topic slug shows once even if two
            // subjects tag it — the backend matches cross-subject
            // on the `topic=` filter anyway.
            val merged = LinkedHashMap<String, Topic>()
            for (subject in subjects) {
                val fetched = runCatching { repository.topics(subject) }
                    .onFailure { Timber.w(it, "quiz topics load failed for %s", subject) }
                    .getOrNull()
                    .orEmpty()
                for (topic in fetched) merged.putIfAbsent(topic.slug, topic)
            }
            _uiState.update {
                it.copy(loadingTopics = false, topics = merged.values.toList())
            }
        }
    }

    fun toggleTopic(slug: String) {
        _uiState.update { state ->
            val next = if (slug in state.selectedTopics) {
                state.selectedTopics - slug
            } else {
                state.selectedTopics + slug
            }
            state.copy(selectedTopics = next)
        }
    }

    fun setQuestionType(type: QuestionType) {
        _uiState.update { it.copy(questionType = type) }
    }

    fun setQuestionCount(count: Int) {
        _uiState.update { it.copy(questionCount = count.coerceIn(1, 50)) }
    }

    fun start() {
        val state = _uiState.value
        if (state.loadingQuestions) return
        viewModelScope.launch {
            _uiState.update { it.copy(loadingQuestions = true, error = null) }
            val fetched = runCatching {
                repository.quiz(
                    subjects = state.selectedSubjects.toList(),
                    topics = state.selectedTopics.toList(),
                    type = state.questionType,
                    count = state.questionCount,
                )
            }.onFailure { Timber.w(it, "quiz start failed") }
                .getOrNull()
                .orEmpty()
            if (fetched.isEmpty()) {
                _uiState.update {
                    it.copy(
                        loadingQuestions = false,
                        error = "No questions returned. Widen the filter or try again.",
                    )
                }
                return@launch
            }
            // Pre-fetch every question's reveal in parallel. The
            // server returns 8 options on /quiz with `is_correct`
            // hidden, but we want to display only 4 (the correct
            // one + 3 stable distractors) and score picks locally
            // without a per-tap round-trip. Revealing upfront is
            // the cleanest way to get there without hitting the
            // server twice per question during play.
            val reveals = withContext(Dispatchers.IO) {
                coroutineScope {
                    fetched.map { q ->
                        async {
                            runCatching { repository.reveal(q.id) }
                                .onFailure { Timber.w(it, "quiz prefetch %d failed", q.id) }
                                .getOrNull()
                        }
                    }.awaitAll()
                }
            }
            val revealedMap = reveals.withIndex()
                .mapNotNull { (i, revealed) -> revealed?.let { i to it } }
                .toMap()
            if (revealedMap.size < fetched.size) {
                // At least one reveal failed — the affected questions
                // will fall back to 8 options and on-demand reveal
                // when the user picks. Not ideal but not a blocker.
                Timber.w("quiz: %d of %d reveals failed", fetched.size - revealedMap.size, fetched.size)
            }
            _uiState.update {
                it.copy(
                    loadingQuestions = false,
                    phase = QuizPhase.Playing,
                    questions = fetched,
                    currentIndex = 0,
                    pickedByIndex = emptyMap(),
                    revealedByIndex = revealedMap,
                    revealing = false,
                )
            }
        }
    }

    fun pickOption(letter: String) {
        val state = _uiState.value
        if (state.phase != QuizPhase.Playing) return
        val index = state.currentIndex
        val question = state.questions.getOrNull(index) ?: return
        if (state.pickedByIndex[index] != null) return

        // Capture the pick. Reveal was pre-fetched at quiz start, so
        // no extra round-trip is needed — we already have the
        // correct answer and the explanation. If the prefetch
        // failed for this one question, fall back to an on-demand
        // /questions/{id} call.
        _uiState.update {
            it.copy(pickedByIndex = it.pickedByIndex + (index to letter))
        }
        if (state.revealedByIndex[index] != null) return

        _uiState.update { it.copy(revealing = true) }
        viewModelScope.launch {
            val revealed = runCatching { repository.reveal(question.id) }
                .onFailure { Timber.w(it, "quiz reveal %d failed", question.id) }
                .getOrNull()
            _uiState.update { state ->
                if (revealed == null) {
                    state.copy(
                        revealing = false,
                        error = "Couldn't reveal the answer. Try next.",
                    )
                } else {
                    state.copy(
                        revealing = false,
                        revealedByIndex = state.revealedByIndex + (index to revealed),
                        error = null,
                    )
                }
            }
        }
    }

    fun next() {
        _uiState.update { state ->
            val nextIndex = state.currentIndex + 1
            if (nextIndex >= state.questions.size) {
                state.copy(phase = QuizPhase.Summary)
            } else {
                state.copy(currentIndex = nextIndex, error = null)
            }
        }
    }

    fun restart() {
        _uiState.update {
            it.copy(
                phase = QuizPhase.Setup,
                questions = emptyList(),
                currentIndex = 0,
                pickedByIndex = emptyMap(),
                revealedByIndex = emptyMap(),
                error = null,
            )
        }
    }
}

enum class QuizPhase { Setup, Playing, Summary }

data class QuizUiState(
    val configured: Boolean = true,
    val phase: QuizPhase = QuizPhase.Setup,
    val loadingSubjects: Boolean = false,
    val loadingTopics: Boolean = false,
    val loadingQuestions: Boolean = false,
    val subjects: List<Subject> = emptyList(),
    val topics: List<Topic> = emptyList(),
    val selectedSubjects: Set<String> = emptySet(),
    val selectedTopics: Set<String> = emptySet(),
    val questionType: QuestionType = QuestionType.Any,
    val questionCount: Int = 10,
    val questions: List<Question> = emptyList(),
    val currentIndex: Int = 0,
    // Keyed by currentIndex (not question.id) so a repeat question
    // in the same quiz wouldn't confuse the map. Server shouldn't
    // return dupes but client stays defensive.
    val pickedByIndex: Map<Int, String> = emptyMap(),
    val revealedByIndex: Map<Int, Question> = emptyMap(),
    val revealing: Boolean = false,
    val error: String? = null,
) {
    val currentQuestion: Question?
        get() = questions.getOrNull(currentIndex)

    val currentPickedLetter: String?
        get() = pickedByIndex[currentIndex]

    val currentRevealed: Question?
        get() = revealedByIndex[currentIndex]

    val currentRevealedCorrectLetter: String?
        get() = currentRevealed?.options?.firstOrNull { it.isCorrect == true }?.letter

    val isLastQuestion: Boolean
        get() = currentIndex >= questions.lastIndex

    // Final-phase score. Counts (index → picked) against the
    // revealed correct letters. Defensively defaults missing reveals
    // to "not scored".
    val score: Int
        get() = pickedByIndex.count { (index, letter) ->
            val correct = revealedByIndex[index]
                ?.options?.firstOrNull { it.isCorrect == true }?.letter
            correct != null && correct == letter
        }
}
