package net.omarss.omono.ui.places

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.feature.places.Place
import net.omarss.omono.feature.places.PlaceCategory

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun PlacesRoute(
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    viewModel: PlacesViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // First-load: fire a refresh once the screen mounts. The user can
    // re-trigger via the refresh icon or by changing category/radius.
    LaunchedEffect(Unit) { viewModel.refresh() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(
            title = { Text("Places nearby") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                }
            },
            actions = {
                IconButton(onClick = { viewModel.refresh(force = true) }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                }
            },
        )

        CategoryChips(
            selected = state.category,
            onSelect = viewModel::selectCategory,
            modifier = Modifier.fillMaxWidth(),
        )

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ConePicker(
                cone = state.coneDegrees,
                onChange = viewModel::setCone,
                modifier = Modifier.weight(1f),
            )
            RadiusPicker(
                radiusMeters = state.radiusMeters,
                onChange = viewModel::setRadius,
                modifier = Modifier.weight(1f),
            )
        }

        HeadingStrip(heading = state.heading)

        if (!state.configured) {
            EmptyState(
                title = "Places backend not configured",
                body = "Add gplaces.api.url and gplaces.api.key to local.properties " +
                    "and rebuild to enable the places search.",
            )
            return@Column
        }

        // No Crossfade — the animated swap between LoadingState and
        // PlaceList reads as flicker when the backend returns in
        // <200 ms. Straight if/else, renders instantly in whatever
        // state we're in. A thin top bar signals "still fetching"
        // without hiding existing results.
        if (state.loading && state.places.isEmpty()) {
            LoadingState()
            return@Column
        }
        if (state.errorMessage != null && state.places.isEmpty()) {
            EmptyState(
                title = "Couldn't load places",
                body = state.errorMessage.orEmpty(),
            )
            return@Column
        }
        if (state.places.isEmpty()) {
            EmptyState(
                title = "Nothing in that direction",
                body = "Widen the cone or pick a different category.",
            )
            return@Column
        }

        if (state.loading) {
            LinearProgressIndicator(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant,
            )
        }
        PlaceList(
            places = state.places,
            heading = state.heading,
            onOpenMap = { place -> launchMapsFor(context, place) },
            onCall = { phone -> launchDialer(context, phone) },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun CategoryChips(
    selected: PlaceCategory,
    onSelect: (PlaceCategory) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        PlaceCategory.entries.forEach { category ->
            FilterChip(
                selected = category == selected,
                onClick = { onSelect(category) },
                label = { Text("${category.icon} ${category.label}") },
                colors = FilterChipDefaults.filterChipColors(),
            )
        }
    }
}

@Composable
private fun ConePicker(
    cone: Float,
    onChange: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    val options = listOf(30f, 60f, 180f)
    val labels = mapOf(30f to "±30°", 60f to "±60°", 180f to "All")
    Column(modifier = modifier) {
        Text(
            text = "Direction",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            options.forEachIndexed { index, value ->
                SegmentedButton(
                    selected = cone == value,
                    onClick = { onChange(value) },
                    shape = SegmentedButtonDefaults.itemShape(index, options.size),
                ) { Text(labels[value] ?: "") }
            }
        }
    }
}

@Composable
private fun RadiusPicker(
    radiusMeters: Int,
    onChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val options = listOf(1_000, 5_000, 20_000)
    val labels = mapOf(1_000 to "1 km", 5_000 to "5 km", 20_000 to "20 km")
    Column(modifier = modifier) {
        Text(
            text = "Radius",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            options.forEachIndexed { index, value ->
                SegmentedButton(
                    selected = radiusMeters == value,
                    onClick = { onChange(value) },
                    shape = SegmentedButtonDefaults.itemShape(index, options.size),
                ) { Text(labels[value] ?: "") }
            }
        }
    }
}

@Composable
private fun HeadingStrip(heading: Float) {
    Text(
        text = "Facing ${heading.toInt()}° · ${compassLabel(heading)}",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
    )
}

@Composable
private fun LoadingState() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator()
    }
}

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

@Composable
private fun PlaceList(
    places: List<Place>,
    heading: Float,
    onOpenMap: (Place) -> Unit,
    onCall: (String) -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(items = places, key = { it.id }) { place ->
            PlaceCard(
                place = place,
                heading = heading,
                onOpenMap = { onOpenMap(place) },
                onCall = { place.phone?.let(onCall) },
            )
        }
    }
}

// Elevated card variant of the old row. Tapping anywhere on the card
// drops the user into their default maps app on the place's coords;
// an inline call button appears when the backend returned a phone number.
@Composable
private fun PlaceCard(
    place: Place,
    heading: Float,
    onOpenMap: () -> Unit,
    onCall: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpenMap),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
        elevation = CardDefaults.elevatedCardElevation(defaultElevation = 2.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CategoryBadge(place.category)
            Spacer(Modifier.size(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = place.name,
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 2,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (place.openNow == true) {
                        Spacer(Modifier.size(6.dp))
                        OpenChip()
                    }
                }
                // Rating line only appears when we actually have one
                // from the gplaces backend.
                place.rating?.let { rating ->
                    Spacer(Modifier.height(2.dp))
                    RatingLine(rating = rating, reviewCount = place.reviewCount)
                }
                val address = place.address
                if (!address.isNullOrBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = address,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                    )
                }
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    DirectionArrow(placeBearing = place.bearingDegrees, heading = heading)
                    Spacer(Modifier.size(6.dp))
                    Text(
                        text = formatDistance(place.distanceMeters),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (!place.phone.isNullOrBlank()) {
                IconButton(onClick = onCall) {
                    Icon(
                        Icons.Filled.Call,
                        contentDescription = "Call ${place.name}",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            }
        }
    }
}

// "★ 4.6 · 1.8K" — compact rating line shown when the backend
// provides a rating. Review count formatted with "K" suffix over a
// thousand because four-digit review counts are uninteresting to
// eyeball at a glance.
@Composable
private fun RatingLine(rating: Float, reviewCount: Int?) {
    val label = buildString {
        append("★ %.1f".format(rating))
        if (reviewCount != null && reviewCount > 0) {
            append(" · ")
            append(formatReviewCount(reviewCount))
        }
    }
    Text(
        text = label,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun OpenChip() {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(Color(0xFF10B981)) // emerald
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(
            text = "Open",
            style = MaterialTheme.typography.labelSmall,
            color = Color.White,
        )
    }
}

private fun formatReviewCount(n: Int): String = when {
    n < 1_000 -> n.toString()
    n < 10_000 -> "%.1fK".format(n / 1000f).removeSuffix(".0K") + "K"
    else -> "${n / 1000}K"
}

// Colored circular badge that holds the category emoji. Uses the
// primary container tint so it reads cleanly on both light and dark
// surfaces without needing a per-category palette.
@Composable
private fun CategoryBadge(category: PlaceCategory) {
    Box(
        modifier = Modifier
            .size(44.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = category.icon,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
        )
    }
}

// Navigation arrow pointing up, rotated by the angle between the
// place's bearing and the user's current heading.
@Composable
private fun DirectionArrow(placeBearing: Float, heading: Float) {
    val delta = ((placeBearing - heading + 360f) % 360f)
    Icon(
        imageVector = Icons.Filled.Navigation,
        contentDescription = null,
        modifier = Modifier
            .size(14.dp)
            .rotate(delta),
        tint = MaterialTheme.colorScheme.primary,
    )
}

// geo:0,0?q=lat,lon(name) — the standard map-intent format that every
// map app on Android handles. Parens around the name produce a labelled
// pin in Google Maps. Name is URL-encoded so commas and & survive.
private fun launchMapsFor(context: Context, place: Place) {
    val label = Uri.encode(place.name)
    val uri = "geo:0,0?q=${place.latitude},${place.longitude}($label)".toUri()
    val intent = Intent(Intent.ACTION_VIEW, uri).apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    runCatching { context.startActivity(intent) }
}

private fun launchDialer(context: Context, phone: String) {
    val intent = Intent(Intent.ACTION_DIAL, "tel:$phone".toUri()).apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    runCatching { context.startActivity(intent) }
}

private fun compassLabel(heading: Float): String {
    val normalized = ((heading + 360f) % 360f).toInt()
    return when (normalized) {
        in 338..360, in 0..22 -> "N"
        in 23..67 -> "NE"
        in 68..112 -> "E"
        in 113..157 -> "SE"
        in 158..202 -> "S"
        in 203..247 -> "SW"
        in 248..292 -> "W"
        in 293..337 -> "NW"
        else -> "?"
    }
}

private fun formatDistance(meters: Double): String = when {
    meters < 1_000 -> "${meters.toInt()} m"
    else -> "%.1f km".format(meters / 1_000)
}
