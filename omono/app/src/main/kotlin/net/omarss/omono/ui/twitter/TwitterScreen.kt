package net.omarss.omono.ui.twitter

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.AsyncImage
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import net.omarss.omono.feature.twitter.CityOption
import net.omarss.omono.feature.twitter.Country
import net.omarss.omono.feature.twitter.CountryOption
import net.omarss.omono.feature.twitter.LocationCatalog
import net.omarss.omono.feature.twitter.LocationOption
import net.omarss.omono.feature.twitter.Tweet

@Composable
fun TwitterRoute(
    contentPadding: PaddingValues = PaddingValues(0.dp),
    viewModel: TwitterViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    TwitterScreen(
        state = uiState,
        contentPadding = contentPadding,
        onOpenFilter = { viewModel.setFilterSheetOpen(true) },
        onCloseFilter = { viewModel.setFilterSheetOpen(false) },
        onToggleLocation = viewModel::toggleLocation,
        onRefresh = viewModel::refresh,
        onLoadMore = viewModel::loadMore,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TwitterScreen(
    state: TwitterUiState,
    contentPadding: PaddingValues,
    onOpenFilter: () -> Unit,
    onCloseFilter: () -> Unit,
    onToggleLocation: (LocationOption) -> Unit,
    onRefresh: () -> Unit,
    onLoadMore: () -> Unit,
) {
    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        topBar = {
            TopAppBar(
                title = { Text("Feed") },
                actions = {
                    IconButton(onClick = onOpenFilter) {
                        Icon(Icons.Filled.FilterList, contentDescription = "Filter locations")
                    }
                },
            )
        },
    ) { inner ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(inner),
        ) {
            ActiveFilterRow(state.filter.selected, onOpenFilter)
            PullToRefreshBox(
                modifier = Modifier.fillMaxSize(),
                isRefreshing = state.loading,
                onRefresh = onRefresh,
            ) {
                when {
                    !state.configured -> NotConfigured()
                    state.tweets.isEmpty() && state.errorMessage != null -> ErrorState(state.errorMessage)
                    state.tweets.isEmpty() && !state.loading -> EmptyState()
                    state.tweets.isEmpty() && state.loading -> LoadingState()
                    else -> TweetList(
                        tweets = state.tweets,
                        loadingMore = state.loadingMore,
                        endReached = state.endReached,
                        errorMessage = state.errorMessage,
                        onLoadMore = onLoadMore,
                    )
                }
            }
        }
    }
    if (state.filterSheetOpen) {
        FilterSheet(
            selected = state.filter.selected,
            onClose = onCloseFilter,
            onToggle = onToggleLocation,
        )
    }
}

// ── Active filter row ───────────────────────────────────────────────
// Above the feed: shows the current selection as removable chips,
// plus an "Add" chip that opens the sheet. Empty selection shows a
// hint chip prompting the user to pick.
@Composable
private fun ActiveFilterRow(
    selected: Set<LocationOption>,
    onOpen: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Stable ordering: countries first, then cities, alphabetical
        // within each group. Keeps the UI calm across rapid toggles.
        val sorted = remember(selected) {
            selected.sortedWith(
                compareBy(
                    { it !is CountryOption },
                    { it.country.code },
                    { it.label },
                ),
            )
        }
        if (sorted.isEmpty()) {
            AssistChip(
                onClick = onOpen,
                label = { Text("Pick locations…") },
            )
        } else {
            sorted.take(3).forEach { opt ->
                AssistChip(
                    onClick = onOpen,
                    label = { Text(opt.label) },
                )
            }
            if (sorted.size > 3) {
                AssistChip(
                    onClick = onOpen,
                    label = { Text("+${sorted.size - 3}") },
                )
            }
        }
    }
}

// ── Tweet list ──────────────────────────────────────────────────────
// LazyColumn with infinite scroll: when the index of the last
// rendered item gets within 5 of the end, we ask the VM for the next
// page. derivedStateOf keeps the trigger off the recomposition hot
// path so we only re-fire when the threshold actually crosses.
@Composable
private fun TweetList(
    tweets: List<Tweet>,
    loadingMore: Boolean,
    endReached: Boolean,
    errorMessage: String?,
    onLoadMore: () -> Unit,
) {
    val listState = rememberLazyListState()
    val nearEnd by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val last = info.visibleItemsInfo.lastOrNull()?.index ?: return@derivedStateOf false
            last >= info.totalItemsCount - 5
        }
    }
    LaunchedEffect(nearEnd, endReached, loadingMore) {
        if (nearEnd && !endReached && !loadingMore) onLoadMore()
    }

    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (errorMessage != null) {
            item {
                Text(
                    text = errorMessage,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        items(tweets, key = Tweet::id) { tweet ->
            TweetCard(tweet)
        }
        if (!endReached) {
            item("__loadmore__") {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(12.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
                }
            }
        } else if (tweets.isNotEmpty()) {
            item("__end__") {
                Text(
                    text = "End of feed",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                )
            }
        }
    }
}

@Composable
private fun TweetCard(tweet: Tweet) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val xUrl = remember(tweet.handle, tweet.id) {
        if (tweet.handle.isNotBlank() && tweet.id.isNotBlank()) {
            "https://x.com/${tweet.handle}/status/${tweet.id}"
        } else null
    }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            // Tapping anywhere on the card outside a link opens the
            // post in the X app (or browser fallback). Lets the user
            // jump to the original thread without hunting for a button.
            .then(
                if (xUrl != null) Modifier.clickable { openExternal(context, xUrl) }
                else Modifier,
            ),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
        ) {
            Avatar(tweet.avatarUrl, tweet.author.ifBlank { tweet.handle })
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = tweet.author.ifBlank { tweet.handle },
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (tweet.handle.isNotBlank()) {
                        Spacer(Modifier.width(6.dp))
                        Text(
                            text = "@${tweet.handle}",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.weight(1f))
                    Text(
                        text = formatRelativeTime(tweet.createdAtMillis),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(4.dp))
                LinkifiedTweetText(
                    text = tweet.text,
                    onClickLink = { url -> openExternal(context, url) },
                )
                Spacer(Modifier.height(6.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    val place = tweet.place?.takeIf { it.isNotBlank() }
                    if (place != null) {
                        Text(
                            text = place,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    EventBadges(tweet.eventCategories)
                    Spacer(Modifier.weight(1f))
                    val stats = buildStatsLine(tweet)
                    if (stats.isNotEmpty()) {
                        Text(
                            text = stats,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

// LinkifiedTweetText renders the body text with embedded URLs styled
// as tappable links. URLs map to ClickableText regions that fire the
// onClickLink lambda — the caller launches an external intent. Falls
// back to a plain Text when there are no URLs (no extra allocations).
@Composable
private fun LinkifiedTweetText(
    text: String,
    onClickLink: (String) -> Unit,
) {
    val matches = remember(text) { URL_REGEX.findAll(text).toList() }
    if (matches.isEmpty()) {
        Text(text = text, style = MaterialTheme.typography.bodyMedium)
        return
    }
    val annotated = remember(text, matches) {
        androidx.compose.ui.text.buildAnnotatedString {
            var cursor = 0
            for (m in matches) {
                if (m.range.first > cursor) {
                    append(text.substring(cursor, m.range.first))
                }
                pushStringAnnotation(tag = "URL", annotation = m.value)
                withStyle(
                    androidx.compose.ui.text.SpanStyle(
                        color = androidx.compose.ui.graphics.Color(0xFF3B82F6),
                        textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline,
                    ),
                ) {
                    append(m.value)
                }
                pop()
                cursor = m.range.last + 1
            }
            if (cursor < text.length) {
                append(text.substring(cursor))
            }
        }
    }
    androidx.compose.foundation.text.ClickableText(
        text = annotated,
        style = MaterialTheme.typography.bodyMedium.copy(
            color = MaterialTheme.colorScheme.onSurface,
        ),
        onClick = { offset ->
            annotated
                .getStringAnnotations(tag = "URL", start = offset, end = offset)
                .firstOrNull()
                ?.let { onClickLink(it.item) }
        },
    )
}

// Matches http/https URLs and bare t.co shortlinks (X sometimes
// strips the protocol on its own shortlinks in the response we get).
private val URL_REGEX = Regex("""https?://\S+|t\.co/\S+""")

// openExternal launches a VIEW intent with FLAG_ACTIVITY_NEW_TASK so
// the Chrome / X chooser handles its own task. Catches the silent
// ActivityNotFoundException case (no browser at all) — extremely rare
// on Android but worth not crashing on.
private fun openExternal(context: android.content.Context, url: String) {
    val cleaned = if (url.startsWith("http")) url else "https://$url"
    val intent = android.content.Intent(
        android.content.Intent.ACTION_VIEW,
        android.net.Uri.parse(cleaned),
    ).apply { addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK) }
    try {
        context.startActivity(intent)
    } catch (_: android.content.ActivityNotFoundException) {
        // No browser installed; silently swallow rather than crash.
    }
}

@Composable
private fun Avatar(url: String?, fallbackLabel: String) {
    val initial = fallbackLabel.firstOrNull()?.uppercaseChar()?.toString() ?: "·"
    Box(
        modifier = Modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)),
        contentAlignment = Alignment.Center,
    ) {
        if (!url.isNullOrBlank()) {
            AsyncImage(
                model = url,
                contentDescription = null,
                modifier = Modifier
                    .fillMaxSize()
                    .clip(CircleShape),
            )
        }
        // Initial sits behind the AsyncImage as a fallback for empty/
        // failed loads — Coil overlays its own bitmap on top once ready.
        Text(
            text = initial,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.primary,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun EventBadges(categories: List<String>) {
    if (categories.isEmpty()) return
    // Show first two badges; "+N" chip when more.
    val visible = categories.take(2)
    val extra = categories.size - visible.size
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        visible.forEach { cat ->
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(MaterialTheme.colorScheme.tertiaryContainer)
                    .padding(horizontal = 8.dp, vertical = 2.dp),
            ) {
                Text(
                    text = cat,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                )
            }
        }
        if (extra > 0) {
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(MaterialTheme.colorScheme.tertiaryContainer)
                    .padding(horizontal = 8.dp, vertical = 2.dp),
            ) {
                Text(
                    text = "+$extra",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                )
            }
        }
    }
}

private fun buildStatsLine(t: Tweet): String = buildString {
    if (t.likeCount > 0) append("♥ ${t.likeCount}")
    if (t.retweetCount > 0) {
        if (isNotEmpty()) append("   ")
        append("⇄ ${t.retweetCount}")
    }
    if (t.replyCount > 0) {
        if (isNotEmpty()) append("   ")
        append("↩ ${t.replyCount}")
    }
}

// ── Filter sheet ────────────────────────────────────────────────────
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FilterSheet(
    selected: Set<LocationOption>,
    onClose: () -> Unit,
    onToggle: (LocationOption) -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(
        onDismissRequest = onClose,
        sheetState = sheetState,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
        ) {
            Text(
                text = "Locations",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "Pick one or more. Country chips include every city below.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))
            LocationCatalog.grouped.forEach { (country, options) ->
                Text(
                    text = country.label,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(4.dp))
                LocationOptionsGrid(options, selected, onToggle)
                Spacer(Modifier.height(12.dp))
            }
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 12.dp),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = onClose) { Text("Done") }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LocationOptionsGrid(
    options: List<LocationOption>,
    selected: Set<LocationOption>,
    onToggle: (LocationOption) -> Unit,
) {
    // Flow-row style — wrap chips across multiple lines naturally.
    androidx.compose.foundation.layout.FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        options.forEach { opt ->
            FilterChip(
                selected = opt in selected,
                onClick = { onToggle(opt) },
                label = { Text(opt.label) },
            )
        }
    }
}

// ── Empty / loading / error / not-configured ────────────────────────
@Composable
private fun NotConfigured() {
    CenterMessage(
        title = "Feed not configured",
        body = "Set `tweets.api.url` in local.properties (default `https://tweets.omarss.net`) and rebuild. See /tweets/README.md.",
    )
}

@Composable
private fun EmptyState() {
    CenterMessage(
        title = "No tweets for this selection",
        body = "Pull to refresh, or pick a different location.",
    )
}

@Composable
private fun ErrorState(message: String) {
    CenterMessage(title = "Couldn't reach the feed", body = message)
}

@Composable
private fun LoadingState() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun CenterMessage(title: String, body: String) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(6.dp))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

// Relative time strings for the timeline. Anything older than ~6 days
// falls through to an absolute date — by that point "1w ago" reads
// less informatively than "26 May".
private val absDateFormatter = SimpleDateFormat("d MMM", Locale.getDefault())
private val absYearFormatter = SimpleDateFormat("d MMM yyyy", Locale.getDefault())

internal fun formatRelativeTime(millis: Long, now: Long = System.currentTimeMillis()): String {
    val delta = now - millis
    val sec = delta / 1000
    return when {
        sec < 0 -> "just now"                        // clock skew safety net
        sec < 45 -> "now"
        sec < 60 * 60 -> "${(sec / 60).coerceAtLeast(1)}m ago"
        sec < 24 * 60 * 60 -> "${sec / 3600}h ago"
        sec < 2 * 24 * 60 * 60 -> "yesterday"
        sec < 7 * 24 * 60 * 60 -> "${sec / 86400}d ago"
        sameYear(millis, now) -> absDateFormatter.format(Date(millis))
        else -> absYearFormatter.format(Date(millis))
    }
}

private fun sameYear(a: Long, b: Long): Boolean {
    val cal = java.util.Calendar.getInstance()
    cal.timeInMillis = a
    val ya = cal.get(java.util.Calendar.YEAR)
    cal.timeInMillis = b
    return ya == cal.get(java.util.Calendar.YEAR)
}
