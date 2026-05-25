package net.omarss.omono.ui.twitter

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import net.omarss.omono.feature.twitter.Country
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
        onCountrySelected = viewModel::selectCountry,
        onRefresh = viewModel::refresh,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TwitterScreen(
    state: TwitterUiState,
    contentPadding: PaddingValues,
    onCountrySelected: (Country) -> Unit,
    onRefresh: () -> Unit,
) {
    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        topBar = {
            TopAppBar(title = { Text("Feed") })
        },
    ) { inner ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(inner),
        ) {
            CountryChips(
                selected = state.country,
                onSelect = onCountrySelected,
            )
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
                        errorMessage = state.errorMessage,
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CountryChips(selected: Country, onSelect: (Country) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Country.entries.forEach { country ->
            FilterChip(
                selected = country == selected,
                onClick = { onSelect(country) },
                label = { Text(country.label) },
            )
        }
    }
}

@Composable
private fun TweetList(tweets: List<Tweet>, errorMessage: String?) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (errorMessage != null) {
            // Show the previous batch + a banner when the latest refresh
            // failed — better than blowing the list away on a flaky
            // network.
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
    }
}

@Composable
private fun TweetCard(tweet: Tweet) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
        ),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = tweet.author.ifBlank { tweet.handle },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                if (tweet.handle.isNotBlank()) {
                    Spacer(Modifier.fillMaxWidth(0f))
                    Text(
                        text = "  @${tweet.handle}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.height(6.dp))
            Text(
                text = tweet.text,
                style = MaterialTheme.typography.bodyMedium,
            )
            Spacer(Modifier.height(8.dp))
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = formatTime(tweet.createdAtMillis),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                val placeLabel = tweet.place?.takeIf { it.isNotBlank() }
                if (placeLabel != null) {
                    Text(
                        text = placeLabel,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                val stats = buildString {
                    if (tweet.likeCount > 0) append("♥ ${tweet.likeCount}")
                    if (tweet.retweetCount > 0) {
                        if (isNotEmpty()) append("   ")
                        append("⇄ ${tweet.retweetCount}")
                    }
                    if (tweet.replyCount > 0) {
                        if (isNotEmpty()) append("   ")
                        append("↩ ${tweet.replyCount}")
                    }
                }
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
        title = "Nothing to show yet",
        body = "Pull to refresh, or try the other country tab.",
    )
}

@Composable
private fun ErrorState(message: String) {
    CenterMessage(
        title = "Couldn't reach the feed",
        body = message,
    )
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
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private val timeFormatter = SimpleDateFormat("EEE d MMM · HH:mm", Locale.getDefault())

private fun formatTime(millis: Long): String = timeFormatter.format(Date(millis))
