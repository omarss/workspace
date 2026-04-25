package net.omarss.omono.ui.prayer.challenge

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.omarss.omono.feature.prayer.AthanPlayer
import net.omarss.omono.feature.prayer.Challenge
import net.omarss.omono.feature.prayer.ChallengeRepository
import net.omarss.omono.feature.prayer.FAJR_CHALLENGE_REQUIRED
import net.omarss.omono.feature.prayer.PrayerKind
import net.omarss.omono.feature.prayer.PrayerNotifier
import javax.inject.Inject

// Runs the Fajr dismiss gate. On init, loads a fresh pool of
// REQUIRED questions. The user picks an option; if correct, we
// advance the `correctCount`. Wrong answers REPLACE the current
// question with a new one (keeping REQUIRED total correct in a row
// from resuming) — the intent is to keep the user engaged until
// they've cleared the bar, not to punish them indefinitely for a
// typo at 5 a.m.
//
// When correctCount reaches FAJR_CHALLENGE_REQUIRED the VM calls
// AthanPlayer.stop() and emits `Result.Dismissed`; the Activity
// finishes itself on that signal.
@HiltViewModel
class AthanChallengeViewModel @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val repository: ChallengeRepository,
    private val athanPlayer: AthanPlayer,
    private val notifier: PrayerNotifier,
) : ViewModel() {

    private val _state = MutableStateFlow(ChallengeUiState())
    val state: StateFlow<ChallengeUiState> = _state.asStateFlow()

    init {
        loadQueue()
    }

    fun selectOption(index: Int) {
        val current = _state.value.current ?: return
        if (_state.value.result != null) return
        if (_state.value.feedback != null) return
        val correct = index == current.correctIndex
        if (correct) {
            val advanced = _state.value.correctCount + 1
            if (advanced >= FAJR_CHALLENGE_REQUIRED) {
                athanPlayer.stop()
                // Dismiss the ongoing Fajr notification so the shade
                // clears alongside the athan stopping.
                notifier.cancel(context, PrayerKind.Fajr)
                _state.update {
                    it.copy(
                        correctCount = advanced,
                        result = ChallengeResult.Dismissed,
                        feedback = Feedback.Correct,
                    )
                }
            } else {
                _state.update {
                    it.copy(correctCount = advanced, feedback = Feedback.Correct)
                }
                // Briefly show correctness, then advance.
                viewModelScope.launch {
                    kotlinx.coroutines.delay(CORRECT_FEEDBACK_MS)
                    advanceToNext()
                }
            }
        } else {
            _state.update { it.copy(feedback = Feedback.Wrong(selected = index)) }
            viewModelScope.launch {
                kotlinx.coroutines.delay(WRONG_FEEDBACK_MS)
                // Replace current with a freshly shuffled question.
                replaceCurrent()
            }
        }
    }

    private fun loadQueue() {
        viewModelScope.launch {
            val all = repository.all()
            if (all.isEmpty()) {
                _state.update {
                    it.copy(
                        result = ChallengeResult.NoQuestions,
                        error = "No challenges bundled — disabling gate.",
                    )
                }
                athanPlayer.stop()
                return@launch
            }
            _state.update {
                it.copy(
                    pool = all,
                    current = all.random(),
                    feedback = null,
                )
            }
        }
    }

    private fun advanceToNext() {
        val pool = _state.value.pool
        if (pool.isEmpty()) return
        val currentId = _state.value.current?.id
        val next = pool.filter { it.id != currentId }.randomOrNull() ?: pool.random()
        _state.update { it.copy(current = next, feedback = null) }
    }

    private fun replaceCurrent() {
        val pool = _state.value.pool
        if (pool.isEmpty()) return
        val currentId = _state.value.current?.id
        val next = pool.filter { it.id != currentId }.randomOrNull() ?: pool.random()
        _state.update { it.copy(current = next, feedback = null) }
    }

    private companion object {
        const val CORRECT_FEEDBACK_MS = 400L
        const val WRONG_FEEDBACK_MS = 800L
    }
}

data class ChallengeUiState(
    val pool: List<Challenge> = emptyList(),
    val current: Challenge? = null,
    val correctCount: Int = 0,
    val feedback: Feedback? = null,
    val result: ChallengeResult? = null,
    val error: String? = null,
)

sealed interface Feedback {
    data object Correct : Feedback
    data class Wrong(val selected: Int) : Feedback
}

sealed interface ChallengeResult {
    data object Dismissed : ChallengeResult
    data object NoQuestions : ChallengeResult
}
