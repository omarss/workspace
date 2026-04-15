package net.omarss.omono.ui.places

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.animation.Crossfade
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.unit.dp
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
                IconButton(onClick = viewModel::refresh) {
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
                title = "TomTom API key not set",
                body = "Add tomtom.api.key=... to local.properties and rebuild " +
                    "to enable the places search.",
            )
            return@Column
        }

        Crossfade(targetState = state, label = "places_state_transition") { currentState ->
            when {
                currentState.loading -> LoadingState()
                currentState.errorMessage != null -> EmptyState(
                    title = "Couldn't load places",
                    body = currentState.errorMessage.orEmpty(),
                )
                currentState.places.isEmpty() -> EmptyState(
                    title = "Nothing in that direction",
                    body = "Widen the cone or pick a different category.",
                )
                else -> PlaceList(places = currentState.places, heading = currentState.heading)
            }
        }
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
private fun PlaceList(places: List<Place>, heading: Float) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(items = places, key = { it.id }) { place ->
            PlaceRow(place = place, heading = heading)
        }
    }
}

@Composable
private fun PlaceRow(place: Place, heading: Float) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = place.category.icon,
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.width(36.dp),
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = place.name,
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            val address = place.address
            if (!address.isNullOrBlank()) {
                Text(
                    text = address,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = formatDistance(place.distanceMeters),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            DirectionArrow(placeBearing = place.bearingDegrees, heading = heading)
        }
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
            .size(16.dp)
            .rotate(delta),
        tint = MaterialTheme.colorScheme.primary,
    )
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
