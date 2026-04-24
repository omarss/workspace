package net.omarss.omono.ui.docs

import androidx.activity.compose.BackHandler
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.feature.docs.DocSubject
import net.omarss.omono.feature.docs.DocSummary
import net.omarss.omono.feature.docs.DocsTtsPlayer
import net.omarss.omono.feature.docs.MarkdownView

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DocsRoute(
    contentPadding: PaddingValues,
    viewModel: DocsViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val ttsState by viewModel.ttsState.collectAsStateWithLifecycle()
    val ttsIndex by viewModel.ttsIndex.collectAsStateWithLifecycle()

    // Hardware/gesture back — walk the 3-level nav back one step. The
    // top level (Subjects) falls through to the system back handler so
    // the user can still exit the app from the tab.
    BackHandler(enabled = state.view != DocsView.Subjects) {
        when (state.view) {
            DocsView.Reader -> viewModel.backToDocs()
            DocsView.Docs -> viewModel.backToSubjects()
            DocsView.Subjects -> {} // unreachable — guarded by `enabled`
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(
            title = { Text(docsTitle(state)) },
            navigationIcon = {
                if (state.view != DocsView.Subjects) {
                    IconButton(onClick = {
                        when (state.view) {
                            DocsView.Reader -> viewModel.backToDocs()
                            DocsView.Docs -> viewModel.backToSubjects()
                            DocsView.Subjects -> {}
                        }
                    }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                        )
                    }
                }
            },
            actions = {
                if (state.view == DocsView.Subjects) {
                    IconButton(onClick = viewModel::refreshSubjects) {
                        Icon(
                            imageVector = Icons.Filled.Refresh,
                            contentDescription = "Refresh subjects",
                        )
                    }
                }
            },
        )

        if (!state.configured) {
            EmptyState(
                title = "Docs backend not configured",
                body = "Add gplaces.api.url and gplaces.api.key to local.properties " +
                    "— the docs service shares them with Places and Quiz.",
            )
            return@Column
        }

        when (state.view) {
            DocsView.Subjects -> SubjectsView(state, viewModel::openSubject)
            DocsView.Docs -> DocListView(state, viewModel::openDoc)
            DocsView.Reader -> ReaderView(
                state = state,
                ttsState = ttsState,
                activeIndex = ttsIndex,
                onPlay = viewModel::playReader,
                onPause = viewModel::pauseReader,
                onResume = viewModel::resumeReader,
                onStop = viewModel::stopTts,
                onSkipForward = viewModel::skipForward,
                onSkipBackward = viewModel::skipBackward,
            )
        }
    }
}

@Composable
private fun docsTitle(state: DocsUiState): String = when (state.view) {
    DocsView.Subjects -> "Docs"
    DocsView.Docs -> state.selectedSubject?.title ?: "Docs"
    DocsView.Reader -> state.reader?.doc?.title
        ?: state.selectedDocSummary?.title
        ?: "Reader"
}

@Composable
private fun SubjectsView(
    state: DocsUiState,
    onTap: (DocSubject) -> Unit,
) {
    if (state.loadingSubjects && state.subjects.isEmpty()) {
        FullLoading()
        return
    }
    if (state.subjects.isEmpty()) {
        EmptyState(
            title = "Docs coming soon",
            body = state.subjectsError
                ?: "The docs service is warming up. Pull down to retry in a moment.",
        )
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(state.subjects, key = { it.slug }) { subject ->
            Card(
                modifier = Modifier.fillMaxWidth(),
                onClick = { onTap(subject) },
                colors = CardDefaults.elevatedCardColors(),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.MenuBook,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = subject.title,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            text = subjectSubtitle(subject),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

private fun subjectSubtitle(subject: DocSubject): String = when {
    subject.docCount < 0 -> subject.slug
    subject.docCount == 1 -> "${subject.slug} · 1 doc"
    else -> "${subject.slug} · ${subject.docCount} docs"
}

@Composable
private fun DocListView(
    state: DocsUiState,
    onTap: (DocSummary) -> Unit,
) {
    if (state.loadingDocs && state.docs.isEmpty()) {
        FullLoading()
        return
    }
    if (state.docs.isEmpty()) {
        EmptyState(
            title = "No docs yet",
            body = state.docsError
                ?: "Nothing's been indexed for this subject yet.",
        )
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(state.docs, key = { "${it.subject}/${it.id}" }) { doc ->
            Card(
                modifier = Modifier.fillMaxWidth(),
                onClick = { onTap(doc) },
                colors = CardDefaults.elevatedCardColors(),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.Article,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.secondary,
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = doc.title,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                        val subtitle = docSubtitle(doc)
                        if (subtitle.isNotBlank()) {
                            Text(
                                text = subtitle,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun docSubtitle(doc: DocSummary): String {
    val parts = buildList {
        doc.sizeBytes?.let { size ->
            val kb = size / 1024.0
            add(if (kb < 1.0) "${size} B" else "%.1f kB".format(kb))
        }
        doc.path?.let { add(it) }
    }
    return parts.joinToString(" · ")
}

@Composable
private fun ReaderView(
    state: DocsUiState,
    ttsState: DocsTtsPlayer.State,
    activeIndex: Int?,
    onPlay: () -> Unit,
    onPause: () -> Unit,
    onResume: () -> Unit,
    onStop: () -> Unit,
    onSkipForward: () -> Unit,
    onSkipBackward: () -> Unit,
) {
    val reader = state.reader
    if (state.loadingReader && reader == null) {
        FullLoading()
        return
    }
    if (reader == null) {
        EmptyState(
            title = "Couldn't load",
            body = state.readerError ?: "Go back and try another doc.",
        )
        return
    }

    // Auto-scroll so the block that TTS is currently speaking stays in
    // view. Re-fired only on index change to avoid fighting the user's
    // manual scrolls — if they scroll away, we don't yank them back.
    val listState = rememberLazyListState()
    LaunchedEffect(activeIndex) {
        val idx = activeIndex ?: return@LaunchedEffect
        // One header item for the doc title + 1 item per block → idx + 1.
        runCatching { listState.animateScrollToItem(idx + 1) }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item(key = "doc-header") {
                Text(
                    text = reader.doc.title,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            // Using the block list directly so we can pass the per-item
            // highlight flag without rebuilding the column on every TTS
            // tick. Each block is its own LazyColumn item so long docs
            // virtualize instead of composing in one pass.
            itemsIndexed(reader.blocks) { index, block ->
                MarkdownView(
                    blocks = listOf(block),
                    modifier = Modifier.fillMaxWidth(),
                    activeBlockIndex = if (index == activeIndex) 0 else null,
                )
            }
            item(key = "bottom-padding") {
                // Leave room so the last block isn't obscured by the
                // floating TTS pill.
                Spacer(modifier = Modifier.height(96.dp))
            }
        }

        TtsPill(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(16.dp),
            ttsState = ttsState,
            utterancesAvailable = reader.utterances.isNotEmpty(),
            onPlay = onPlay,
            onPause = onPause,
            onResume = onResume,
            onStop = onStop,
            onSkipForward = onSkipForward,
            onSkipBackward = onSkipBackward,
        )
    }
}

@Composable
private fun TtsPill(
    modifier: Modifier = Modifier,
    ttsState: DocsTtsPlayer.State,
    utterancesAvailable: Boolean,
    onPlay: () -> Unit,
    onPause: () -> Unit,
    onResume: () -> Unit,
    onStop: () -> Unit,
    onSkipForward: () -> Unit,
    onSkipBackward: () -> Unit,
) {
    Surface(
        modifier = modifier,
        tonalElevation = 4.dp,
        shadowElevation = 6.dp,
        color = MaterialTheme.colorScheme.surfaceContainerHigh,
        shape = MaterialTheme.shapes.extraLarge,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = onSkipBackward,
                enabled = ttsState != DocsTtsPlayer.State.Unavailable,
            ) {
                Icon(Icons.Filled.SkipPrevious, contentDescription = "Previous block")
            }

            when (ttsState) {
                DocsTtsPlayer.State.Speaking -> FilledIconButton(onClick = onPause) {
                    Icon(Icons.Filled.Pause, contentDescription = "Pause")
                }
                DocsTtsPlayer.State.Paused -> FilledIconButton(onClick = onResume) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = "Resume")
                }
                DocsTtsPlayer.State.Idle -> FilledIconButton(
                    onClick = onPlay,
                    enabled = utterancesAvailable,
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = "Read aloud")
                }
                DocsTtsPlayer.State.Unavailable -> FilledIconButton(
                    onClick = {},
                    enabled = false,
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = "TTS not available")
                }
            }

            IconButton(
                onClick = onSkipForward,
                enabled = ttsState != DocsTtsPlayer.State.Unavailable,
            ) {
                Icon(Icons.Filled.SkipNext, contentDescription = "Next block")
            }

            if (ttsState == DocsTtsPlayer.State.Speaking ||
                ttsState == DocsTtsPlayer.State.Paused
            ) {
                IconButton(onClick = onStop) {
                    Icon(Icons.Filled.Stop, contentDescription = "Stop reader")
                }
            }
        }
    }
}

@Composable
private fun FullLoading() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun EmptyState(title: String, body: String) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            imageVector = Icons.AutoMirrored.Filled.MenuBook,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
