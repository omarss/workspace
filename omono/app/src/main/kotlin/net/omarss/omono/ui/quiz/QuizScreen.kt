package net.omarss.omono.ui.quiz

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.feature.quiz.Question
import net.omarss.omono.feature.quiz.QuestionType
import net.omarss.omono.feature.quiz.QuizOption

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun QuizRoute(
    contentPadding: PaddingValues,
    viewModel: QuizViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(
            title = {
                Text(
                    when (state.phase) {
                        QuizPhase.Setup -> "Quiz"
                        QuizPhase.Playing -> "Question ${state.currentIndex + 1} / ${state.questions.size}"
                        QuizPhase.Summary -> "Quiz summary"
                    },
                )
            },
        )

        if (!state.configured) {
            EmptyState(
                title = "Quiz backend not configured",
                body = "Add gplaces.api.url and gplaces.api.key to local.properties " +
                    "— the MCQ service shares them with Places.",
            )
            return@Column
        }

        when (state.phase) {
            QuizPhase.Setup -> SetupView(
                state = state,
                onToggleSubject = viewModel::toggleSubject,
                onClearSubjects = viewModel::clearSubjects,
                onToggleTopic = viewModel::toggleTopic,
                onTypeChange = viewModel::setQuestionType,
                onCountChange = viewModel::setQuestionCount,
                onStart = viewModel::start,
            )
            QuizPhase.Playing -> PlayingView(
                state = state,
                onPick = viewModel::pickOption,
                onNext = viewModel::next,
                onBackToSetup = viewModel::restart,
            )
            QuizPhase.Summary -> SummaryView(
                state = state,
                onRestart = viewModel::restart,
            )
        }
    }
}

// ------------------------------------------------------------------
// Setup
// ------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun SetupView(
    state: QuizUiState,
    onToggleSubject: (String) -> Unit,
    onClearSubjects: () -> Unit,
    onToggleTopic: (String) -> Unit,
    onTypeChange: (QuestionType) -> Unit,
    onCountChange: (Int) -> Unit,
    onStart: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        // Subjects ---------------------------------------------------
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "Subjects",
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.weight(1f),
                )
                if (state.selectedSubjects.isNotEmpty()) {
                    TextButton(onClick = onClearSubjects) { Text("Clear") }
                }
            }
            Text(
                text = if (state.selectedSubjects.isEmpty()) {
                    "Leave empty for a bank-wide mix."
                } else {
                    "${state.selectedSubjects.size} selected"
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (state.loadingSubjects) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }
            SubjectChipFlow(
                subjects = state.subjects,
                selected = state.selectedSubjects,
                onToggle = onToggleSubject,
            )
        }

        // Topics (appear only when ≥1 subject is chosen) -------------
        if (state.selectedSubjects.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    text = "Topics",
                    style = MaterialTheme.typography.labelLarge,
                )
                Text(
                    text = if (state.selectedTopics.isEmpty()) {
                        "Optional — tap one or more to combine (OR)."
                    } else {
                        "${state.selectedTopics.size} selected · any match"
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (state.loadingTopics) {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                } else if (state.topics.isEmpty()) {
                    Text(
                        text = "No topics available.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    TopicChipFlow(
                        topics = state.topics.map { it.slug to it.title },
                        selected = state.selectedTopics,
                        onToggle = onToggleTopic,
                    )
                }
            }
        }

        // Type -------------------------------------------------------
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                text = "Question type",
                style = MaterialTheme.typography.labelLarge,
            )
            val types = QuestionType.entries
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                types.forEachIndexed { index, t ->
                    SegmentedButton(
                        selected = state.questionType == t,
                        onClick = { onTypeChange(t) },
                        shape = SegmentedButtonDefaults.itemShape(index, types.size),
                        label = {
                            Text(
                                text = when (t) {
                                    QuestionType.Any -> "Any"
                                    QuestionType.Knowledge -> "Knowledge"
                                    QuestionType.Analytical -> "Analytical"
                                    QuestionType.ProblemSolving -> "Problem"
                                },
                                maxLines = 1,
                                softWrap = false,
                            )
                        },
                    )
                }
            }
        }

        // Count ------------------------------------------------------
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "Questions",
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = state.questionCount.toString(),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Slider(
                value = state.questionCount.toFloat(),
                onValueChange = { onCountChange(it.toInt()) },
                valueRange = 1f..50f,
                steps = 48,
            )
        }

        state.error?.let { msg ->
            Text(
                text = msg,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        Button(
            onClick = onStart,
            enabled = !state.loadingQuestions,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (state.loadingQuestions) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                )
                Spacer(Modifier.width(8.dp))
                Text("Loading…")
            } else {
                Text("Start quiz")
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

// Chip "flow" via a horizontally scrollable row. Subjects can be
// many (43 today) so a grid would add a lot of visual noise; a
// scroll band is quick to scan and matches the pattern used on
// Places/Compass chip rows.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SubjectChipFlow(
    subjects: List<net.omarss.omono.feature.quiz.Subject>,
    selected: Set<String>,
    onToggle: (String) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        subjects.forEach { subject ->
            FilterChip(
                selected = subject.slug in selected,
                onClick = { onToggle(subject.slug) },
                label = { Text("${subject.title} · ${subject.totalQuestions}") },
                colors = FilterChipDefaults.filterChipColors(),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TopicChipFlow(
    topics: List<Pair<String, String>>,
    selected: Set<String>,
    onToggle: (String) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        topics.forEach { (slug, title) ->
            FilterChip(
                selected = slug in selected,
                onClick = { onToggle(slug) },
                label = { Text(title) },
                colors = FilterChipDefaults.filterChipColors(),
            )
        }
    }
}

// ------------------------------------------------------------------
// Playing
// ------------------------------------------------------------------

@Composable
private fun PlayingView(
    state: QuizUiState,
    onPick: (String) -> Unit,
    onNext: () -> Unit,
    onBackToSetup: () -> Unit,
) {
    val question = state.currentQuestion ?: return
    val revealed = state.currentRevealed
    val picked = state.currentPickedLetter
    val progress = ((state.currentIndex + 1).toFloat() / state.questions.size)
        .coerceIn(0f, 1f)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        LinearProgressIndicator(
            progress = { progress },
            modifier = Modifier.fillMaxWidth(),
        )

        // Meta row: subject · type · difficulty
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            MetaPill(text = question.subject)
            MetaPill(text = typeLabel(question.type))
            MetaPill(text = "Difficulty ${question.difficulty}")
        }

        // Stem
        Text(
            text = question.stem,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )

        // Options — use the revealed copy when available (matches
        // the letter→text mapping the user sees here; the server
        // randomises on every call) and trim to four: the correct
        // answer plus three stable distractors seeded by the
        // question id. If the reveal prefetch failed for this
        // question we fall back to all eight options from /quiz.
        val optionsToRender = buildQuizOptions(
            revealed = revealed,
            fallback = question.options,
            seed = question.id.toLong(),
        )
        val hasPicked = picked != null
        optionsToRender.forEach { option ->
            OptionCard(
                option = option,
                picked = picked == option.letter,
                hasPicked = hasPicked,
                correctLetter = state.currentRevealedCorrectLetter,
                enabled = !hasPicked,
                onPick = { onPick(option.letter) },
            )
        }

        if (state.revealing) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(
                    modifier = Modifier.size(16.dp),
                    strokeWidth = 2.dp,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "Checking answer…",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        revealed?.explanation?.takeIf { it.isNotBlank() }?.let { explanation ->
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
                ),
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Explanation",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = explanation,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }

        state.error?.let { msg ->
            Text(
                text = msg,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedButton(
                onClick = onBackToSetup,
                modifier = Modifier.weight(1f),
            ) { Text("End quiz") }
            Button(
                onClick = onNext,
                enabled = picked != null,
                modifier = Modifier.weight(1f),
            ) {
                Text(if (state.isLastQuestion) "Finish" else "Next")
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun MetaPill(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSecondaryContainer,
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(MaterialTheme.colorScheme.secondaryContainer)
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

// Option card: neutral surface before the user picks, tinted
// green/red after. Correct/incorrect tinting is gated on the
// user actually committing to an answer — answers are prefetched
// at quiz start for latency reasons, but the card must stay opaque
// to which one is correct until the user has chosen.
@Composable
private fun OptionCard(
    option: QuizOption,
    picked: Boolean,
    hasPicked: Boolean,
    correctLetter: String?,
    enabled: Boolean,
    onPick: () -> Unit,
) {
    val isCorrectOption = option.isCorrect == true
    val isPickedAndCorrect = picked && isCorrectOption
    val isPickedAndWrong = picked && !isCorrectOption

    val containerColor = when {
        !hasPicked -> MaterialTheme.colorScheme.surfaceContainerHighest
        isPickedAndCorrect -> Color(0xFFDCFCE7) // emerald 100
        isPickedAndWrong -> Color(0xFFFEE2E2) // red 100
        option.letter == correctLetter -> Color(0xFFDCFCE7) // reveal correct when user picked wrong
        else -> MaterialTheme.colorScheme.surfaceContainerHighest
    }
    val borderColor = when {
        !hasPicked -> Color.Transparent
        isPickedAndCorrect -> Color(0xFF10B981) // emerald 500
        isPickedAndWrong -> Color(0xFFDC2626) // red 600
        option.letter == correctLetter -> Color(0xFF10B981)
        else -> Color.Transparent
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .then(
                if (enabled) Modifier.clickable(onClick = onPick) else Modifier,
            ),
        colors = CardDefaults.cardColors(containerColor = containerColor),
        border = if (borderColor != Color.Transparent) {
            androidx.compose.foundation.BorderStroke(1.5.dp, borderColor)
        } else null,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = option.letter,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            Spacer(Modifier.width(12.dp))
            Text(
                text = option.text,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.weight(1f),
            )
            if (hasPicked) {
                when {
                    isPickedAndCorrect -> Icon(
                        imageVector = Icons.Filled.Check,
                        contentDescription = "Correct",
                        tint = Color(0xFF10B981),
                    )
                    isPickedAndWrong -> Icon(
                        imageVector = Icons.Filled.Close,
                        contentDescription = "Incorrect",
                        tint = Color(0xFFDC2626),
                    )
                    option.letter == correctLetter -> Icon(
                        imageVector = Icons.Filled.Check,
                        contentDescription = "Correct answer",
                        tint = Color(0xFF10B981),
                    )
                    else -> Unit
                }
            }
        }
    }
}

private fun typeLabel(type: QuestionType) = when (type) {
    QuestionType.Any -> "Any"
    QuestionType.Knowledge -> "Knowledge"
    QuestionType.Analytical -> "Analytical"
    QuestionType.ProblemSolving -> "Problem solving"
}

// Picks four options to show for one question: the correct answer
// plus three randomly-chosen distractors, reshuffled into stable
// order so the letters A–D (or whichever the server emitted) keep
// positions across recompositions.
//
// Seeded by the question id → two successive frames of the same
// question render the same four options. Different questions get
// different subsets because the seed differs. If the reveal
// prefetch failed (revealed == null) we fall through to the full
// eight-option list so the user still has something to pick.
private const val OPTIONS_PER_QUESTION: Int = 4

private fun buildQuizOptions(
    revealed: Question?,
    fallback: List<QuizOption>,
    seed: Long,
): List<QuizOption> {
    if (revealed == null) return fallback
    val options = revealed.options
    if (options.size <= OPTIONS_PER_QUESTION) return options
    val correct = options.firstOrNull { it.isCorrect == true } ?: return options
    val wrong = options.filter { it.isCorrect != true }
    val rng = kotlin.random.Random(seed)
    val distractors = wrong.shuffled(rng).take(OPTIONS_PER_QUESTION - 1)
    // Reshuffle correct + distractors together so the correct
    // answer isn't always in the same slot; use a derived seed so
    // this shuffle is *also* stable per question.
    return (listOf(correct) + distractors).shuffled(kotlin.random.Random(seed xor 0x5F3759DFL))
}

// ------------------------------------------------------------------
// Summary
// ------------------------------------------------------------------

@Composable
private fun SummaryView(state: QuizUiState, onRestart: () -> Unit) {
    val total = state.questions.size
    val score = state.score
    val pct = if (total > 0) (score * 100 / total) else 0
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = "$score / $total",
            style = MaterialTheme.typography.displayMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
        )
        Text(
            text = "$pct% correct",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        // Per-question review — one row per question with the
        // picked letter, the correct letter, and the stem preview.
        state.questions.forEachIndexed { index, question ->
            val picked = state.pickedByIndex[index]
            val revealed = state.revealedByIndex[index]
            val correct = revealed?.options?.firstOrNull { it.isCorrect == true }?.letter
            val isCorrect = picked != null && correct != null && picked == correct
            SummaryRow(
                index = index + 1,
                stem = question.stem,
                picked = picked,
                correct = correct,
                isCorrect = isCorrect,
            )
        }

        Spacer(Modifier.height(12.dp))
        Button(onClick = onRestart, modifier = Modifier.fillMaxWidth()) {
            Text("New quiz")
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun SummaryRow(
    index: Int,
    stem: String,
    picked: String?,
    correct: String?,
    isCorrect: Boolean,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (isCorrect) {
                Color(0xFFDCFCE7)
            } else {
                MaterialTheme.colorScheme.surfaceContainerHighest
            },
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Box(
                modifier = Modifier
                    .size(28.dp)
                    .clip(CircleShape)
                    .background(
                        if (isCorrect) Color(0xFF10B981) else Color(0xFFDC2626),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = if (isCorrect) Icons.Filled.Check else Icons.Filled.Close,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(16.dp),
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Q$index",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = stem,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 2,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = buildString {
                        append("Picked ")
                        append(picked ?: "—")
                        if (correct != null) {
                            append(" · correct ")
                            append(correct)
                        }
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

// ------------------------------------------------------------------
// Empty state (backend-not-configured)
// ------------------------------------------------------------------

@Composable
private fun EmptyState(title: String, body: String) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
