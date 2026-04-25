package net.omarss.omono.ui.prayer.challenge

import android.app.KeyguardManager
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import dagger.hilt.android.AndroidEntryPoint
import net.omarss.omono.core.designsystem.theme.OmonoTheme
import net.omarss.omono.feature.prayer.Challenge
import net.omarss.omono.feature.prayer.FAJR_CHALLENGE_REQUIRED

// Full-screen activity that gates the Fajr athan. Launched via the
// full-screen-intent notification posted by the prayer alarm
// receiver when the athan starts playing and the user has
// requireChallengeToStop = true. WindowManager flags ask the
// platform to show over the lock screen and to wake the display.
@AndroidEntryPoint
class AthanChallengeActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        showWhenLocked()
        setContent {
            OmonoTheme(darkTheme = true) {
                val vm: AthanChallengeViewModel = viewModel()
                val state by vm.state.collectAsState()
                LaunchedEffect(state.result) {
                    if (state.result != null) finish()
                }
                ChallengeScreen(
                    state = state,
                    onSelect = vm::selectOption,
                )
            }
        }
    }

    // Show-over-lockscreen + wake-the-display pattern used by every
    // alarm-clock / call-UI app. API 27+ has the named setters; older
    // devices still need the WindowManager flags.
    private fun showWhenLocked() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            val km = getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
            km?.requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD or
                    WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            )
        }
        // Always keep the display awake for the duration of the gate.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
}

@androidx.compose.runtime.Composable
private fun ChallengeScreen(
    state: ChallengeUiState,
    onSelect: (Int) -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 28.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            HeaderRow(state)
            state.current?.let { question ->
                QuestionCard(
                    question = question,
                    feedback = state.feedback,
                    onSelect = onSelect,
                )
            }
            if (state.error != null) {
                Text(
                    text = state.error!!,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun HeaderRow(state: ChallengeUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            text = "Fajr is calling",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = "Answer $FAJR_CHALLENGE_REQUIRED questions correctly in a row to silence the athan.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            repeat(FAJR_CHALLENGE_REQUIRED) { index ->
                val filled = index < state.correctCount
                Box(
                    modifier = Modifier
                        .size(18.dp)
                        .clip(CircleShape)
                        .background(
                            if (filled) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.surfaceVariant,
                        ),
                )
            }
            Spacer(Modifier.width(8.dp))
            state.current?.let {
                AssistChip(
                    onClick = {},
                    label = { Text(it.category.display) },
                    colors = AssistChipDefaults.assistChipColors(),
                )
            }
        }
        LinearProgressIndicator(
            progress = { state.correctCount.toFloat() / FAJR_CHALLENGE_REQUIRED },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@androidx.compose.runtime.Composable
private fun QuestionCard(
    question: Challenge,
    feedback: Feedback?,
    onSelect: (Int) -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = question.stem,
                style = MaterialTheme.typography.titleLarge.copy(fontSize = 20.sp),
                fontWeight = FontWeight.Medium,
            )
            question.options.forEachIndexed { idx, option ->
                OptionRow(
                    label = option,
                    idx = idx,
                    feedback = feedback,
                    correctIndex = question.correctIndex,
                    onClick = { onSelect(idx) },
                )
            }
            val explanation = question.explanation
            if (feedback is Feedback.Wrong && explanation != null) {
                Text(
                    text = explanation,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun OptionRow(
    label: String,
    idx: Int,
    feedback: Feedback?,
    correctIndex: Int,
    onClick: () -> Unit,
) {
    val bg = when (feedback) {
        null -> MaterialTheme.colorScheme.surfaceVariant
        Feedback.Correct -> if (idx == correctIndex) {
            MaterialTheme.colorScheme.primaryContainer
        } else MaterialTheme.colorScheme.surfaceVariant
        is Feedback.Wrong -> when (idx) {
            feedback.selected -> MaterialTheme.colorScheme.errorContainer
            correctIndex -> MaterialTheme.colorScheme.primaryContainer
            else -> MaterialTheme.colorScheme.surfaceVariant
        }
    }
    val icon: @androidx.compose.runtime.Composable (() -> Unit)? = when {
        feedback == null -> null
        idx == correctIndex -> {
            { Icon(Icons.Filled.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary) }
        }
        feedback is Feedback.Wrong && idx == feedback.selected -> {
            { Icon(Icons.Filled.Close, contentDescription = null, tint = MaterialTheme.colorScheme.error) }
        }
        else -> null
    }
    val baseModifier = Modifier
        .fillMaxWidth()
        .clip(RoundedCornerShape(12.dp))
        .background(bg)
    // Only tappable while no feedback is being shown — avoids a
    // mid-feedback re-click registering as a second answer.
    val rowModifier = if (feedback == null) {
        baseModifier.clickable(onClick = onClick)
    } else baseModifier
    Row(
        modifier = rowModifier.padding(horizontal = 14.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "${'A' + idx}.",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.width(30.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(4.dp))
        Text(
            text = label,
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.bodyLarge,
        )
        if (icon != null) {
            Spacer(Modifier.width(8.dp))
            icon()
        }
    }
}

