package net.omarss.omono.ui.compass

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Mosque
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.feature.places.PlaceCategory
import net.omarss.omono.ui.places.visual

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CompassRoute(
    contentPadding: PaddingValues,
    viewModel: CompassViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(
            title = { Text("Compass") },
            actions = {
                IconButton(onClick = viewModel::refresh) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                }
            },
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            val markers = buildCompassMarkers(
                qiblaBearingDeg = state.qiblaBearingDeg,
                nearestMosqueBearingDeg = state.nearestMosque?.bearingDeg,
                nearestMosqueDistance = state.nearestMosque?.distanceMeters,
                categoryRows = state.categoryRows,
            )
            CompassRose(
                headingDeg = state.headingDeg,
                markers = markers,
                modifier = Modifier.fillMaxWidth(),
            )

            // Chip row for quick-toggle "nearest X" pins. Tapping a
            // chip asks the ViewModel to look up the nearest place in
            // that category; the result is rendered as its own bearing
            // row below, and as a coloured dot on the compass ring.
            CategoryToggleRow(
                enabled = state.enabledCategories,
                onToggle = viewModel::toggleCategory,
            )

            // Secondary read-outs beneath the dial. These spell out the
            // three bearings so the user doesn't have to eyeball the
            // small coloured dots on the ring.
            BearingRow(
                label = "North (true)",
                bearingDeg = 0f,
                color = Color(0xFFEF4444),
                icon = Icons.Filled.Explore,
            )
            state.qiblaBearingDeg?.let {
                BearingRow(
                    label = "Mecca (Qibla)",
                    bearingDeg = it,
                    color = Color(0xFFF59E0B),
                    icon = Icons.Filled.Mosque,
                )
            }
            state.nearestMosque?.let { mosque ->
                BearingRow(
                    label = mosque.name ?: "Nearest mosque",
                    bearingDeg = mosque.bearingDeg,
                    color = Color(0xFF10B981),
                    icon = PlaceCategory.MOSQUE.visual().icon,
                    subtitle = "${formatMetres(mosque.distanceMeters)} · heading " +
                        compassLabel(mosque.bearingDeg),
                    // When the winner came from the gplaces backend we
                    // have a CID → open the full Maps place card
                    // (reviews, hours, photos). When it came from the
                    // offline OSM directory we drop a labelled pin.
                    onClick = {
                        launchMapsPlace(
                            context = context,
                            cid = mosque.cid,
                            label = mosque.name ?: "Mosque",
                            lat = mosque.latitude,
                            lon = mosque.longitude,
                        )
                    },
                )
            }

            // One bearing row per user-enabled category with a
            // resolved lookup. Sorted by distance so the closest
            // pin sits near the top of the list.
            state.categoryRows.forEach { row ->
                BearingRow(
                    label = row.name.ifBlank { row.category.label },
                    bearingDeg = row.bearingDeg,
                    color = row.category.visual().tint,
                    icon = row.category.visual().icon,
                    subtitle = "${row.category.label} · ${formatMetres(row.distanceMeters)} · heading " +
                        compassLabel(row.bearingDeg),
                    onClick = {
                        launchMapsPlace(
                            context = context,
                            cid = row.cid,
                            label = row.name.ifBlank { row.category.label },
                            lat = row.latitude,
                            lon = row.longitude,
                        )
                    },
                )
            }

            if (state.errorMessage != null) {
                Spacer(Modifier.height(8.dp))
                Text(
                    text = state.errorMessage.orEmpty(),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center,
                )
            }
        }
    }
}

private fun buildCompassMarkers(
    qiblaBearingDeg: Float?,
    nearestMosqueBearingDeg: Float?,
    nearestMosqueDistance: Double?,
    categoryRows: List<CategoryRow>,
): List<CompassMarker> = buildList {
    // North stays a plain dot — it's a cardinal reference, not a
    // place pin, and the big red "N" cardinal label already carries
    // its identity.
    add(CompassMarker(bearingDeg = 0f, color = Color(0xFFEF4444), label = "North"))
    qiblaBearingDeg?.let {
        add(
            CompassMarker(
                bearingDeg = it,
                color = Color(0xFFF59E0B),
                label = "Mecca",
                icon = Icons.Filled.Mosque,
            ),
        )
    }
    nearestMosqueBearingDeg?.let { bearing ->
        val distLabel = nearestMosqueDistance?.let { " · ${formatMetres(it)}" }.orEmpty()
        add(
            CompassMarker(
                bearingDeg = bearing,
                color = Color(0xFF10B981),
                label = "Mosque$distLabel",
                icon = PlaceCategory.MOSQUE.visual().icon,
            ),
        )
    }
    categoryRows.forEach { row ->
        val visual = row.category.visual()
        add(
            CompassMarker(
                bearingDeg = row.bearingDeg,
                color = visual.tint,
                label = "${row.category.label} · ${formatMetres(row.distanceMeters)}",
                icon = visual.icon,
            ),
        )
    }
}

// Horizontally-scrollable row of toggleable category chips. Order is
// driving-utility first (fuel, pharmacy, hospital), then common errands
// (ATM, bank, grocery, mall), then daily services (gym, park, salon).
// Deliberately smaller than the full PlaceCategory set on the Places
// tab — compass pins should feel curated rather than overwhelming.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CategoryToggleRow(
    enabled: Set<PlaceCategory>,
    onToggle: (PlaceCategory) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        COMPASS_QUICK_CATEGORIES.forEach { category ->
            val visual = category.visual()
            FilterChip(
                selected = category in enabled,
                onClick = { onToggle(category) },
                label = { Text(category.label) },
                leadingIcon = {
                    Icon(
                        imageVector = visual.icon,
                        contentDescription = null,
                        tint = visual.tint,
                        modifier = Modifier.size(16.dp),
                    )
                },
                colors = FilterChipDefaults.filterChipColors(),
            )
        }
    }
}

// Every category the backend supports, ordered driving-utility
// first (fuel / pharmacy / hospital / transit), then common errands
// (atm / bank / grocery / mall / ev / park / gym / salon / laundry),
// then food parents (restaurant / fast food / coffee / bakery / juice),
// then standalone niches (library / bookstore / clinic / museum /
// cultural_site / brunch / mosque), then cuisine subcats. The chip
// row is horizontally scrollable so length isn't an issue, but the
// ordering keeps the most-likely picks near the leading edge.
private val COMPASS_QUICK_CATEGORIES: List<PlaceCategory> = listOf(
    // Driving utility
    PlaceCategory.FUEL,
    PlaceCategory.PHARMACY,
    PlaceCategory.HOSPITAL,
    PlaceCategory.TRANSIT,
    // Common errands
    PlaceCategory.ATM,
    PlaceCategory.BANK,
    PlaceCategory.GROCERY,
    PlaceCategory.MALL,
    PlaceCategory.EV_CHARGER,
    PlaceCategory.CAR_WASH,
    PlaceCategory.PARK,
    PlaceCategory.GYM,
    PlaceCategory.SALON,
    PlaceCategory.LAUNDRY,
    PlaceCategory.POST_OFFICE,
    // Food parents
    PlaceCategory.COFFEE,
    PlaceCategory.RESTAURANT,
    PlaceCategory.FAST_FOOD,
    PlaceCategory.BAKERY,
    PlaceCategory.JUICE,
    // Niches
    PlaceCategory.LIBRARY,
    PlaceCategory.BOOKSTORE,
    PlaceCategory.CLINIC,
    PlaceCategory.MUSEUM,
    PlaceCategory.CULTURAL_SITE,
    PlaceCategory.BRUNCH,
    PlaceCategory.MOSQUE,
) + PlaceCategory.entries.filter { it.isCuisine }

@Composable
private fun BearingRow(
    label: String,
    bearingDeg: Float,
    color: Color,
    subtitle: String? = null,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    onClick: (() -> Unit)? = null,
) {
    val rowModifier = Modifier
        .fillMaxWidth()
        .let { m -> if (onClick != null) m.clickable(onClick = onClick) else m }
        .padding(horizontal = 4.dp, vertical = if (onClick != null) 6.dp else 0.dp)
    Row(
        modifier = rowModifier,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Leading glyph: a category-specific Material icon when we
        // have one, otherwise the legacy coloured dot so the row
        // still carries its colour identity for a legend.
        if (icon != null) {
            IconBadge(icon = icon, tint = color)
        } else {
            ColoredDot(color)
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = label,
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            if (subtitle != null) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Text(
            text = bearingText(bearingDeg),
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.End,
        )
        if (onClick != null) {
            Spacer(Modifier.width(8.dp))
            Icon(
                imageVector = Icons.Filled.Navigation,
                contentDescription = "Navigate to $label",
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

// Opens the Google Maps place card for the given place, preferring a
// `?cid=<n>` deep link when the backend supplied one so the user lands
// on the full detail view (reviews, photos, hours) rather than a bare
// lat/lon pin. The `geo:` fallback still labels the pin with the
// place's name, so even without a CID the result feels like a real
// place page with a Directions button ready to tap. Mirrors the
// PlacesScreen logic so both tabs feel identical when the user taps a
// result.
private fun launchMapsPlace(
    context: Context,
    cid: String?,
    label: String,
    lat: Double,
    lon: Double,
) {
    val uri = if (!cid.isNullOrBlank()) {
        "https://www.google.com/maps?cid=$cid".toUri()
    } else {
        val encodedLabel = android.net.Uri.encode(label)
        "geo:0,0?q=$lat,$lon($encodedLabel)".toUri()
    }
    val intent = Intent(Intent.ACTION_VIEW, uri).apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    runCatching { context.startActivity(intent) }
}

@Composable
private fun ColoredDot(color: Color) {
    Canvas(modifier = Modifier.size(12.dp)) {
        drawCircle(color)
    }
}

// Circular 32 dp icon badge — tint-coloured Material icon over a
// 14 % alpha wash of the same colour. Matches the pattern used on
// the Places tab's CategoryBadge so the compass row reads as
// "this is a pharmacy / fuel / mosque" without needing a separate
// colour legend.
@Composable
private fun IconBadge(icon: ImageVector, tint: Color) {
    Box(
        modifier = Modifier
            .size(32.dp)
            .clip(CircleShape)
            .background(tint.copy(alpha = 0.14f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = tint,
            modifier = Modifier.size(20.dp),
        )
    }
}

private fun bearingText(bearingDeg: Float): String {
    val n = ((bearingDeg % 360f) + 360f) % 360f
    return "${compassLabel(n)} · ${n.toInt()}°"
}

private fun formatMetres(m: Double): String =
    if (m < 1000) "${m.toInt()} m" else "%.1f km".format(m / 1000.0)
