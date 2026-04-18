package net.omarss.omono.ui.compass

import androidx.compose.foundation.Canvas
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
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CompassRoute(
    contentPadding: PaddingValues,
    viewModel: CompassViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

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
            )
            CompassRose(
                headingDeg = state.headingDeg,
                markers = markers,
                modifier = Modifier.fillMaxWidth(),
            )

            // Secondary read-outs beneath the dial. These spell out the
            // three bearings so the user doesn't have to eyeball the
            // small coloured dots on the ring.
            BearingRow(
                label = "North (true)",
                bearingDeg = 0f,
                color = Color(0xFFEF4444),
            )
            state.qiblaBearingDeg?.let {
                BearingRow(
                    label = "Mecca (Qibla)",
                    bearingDeg = it,
                    color = Color(0xFFF59E0B),
                )
            }
            state.nearestMosque?.let { mosque ->
                BearingRow(
                    label = mosque.name ?: "Nearest mosque",
                    bearingDeg = mosque.bearingDeg,
                    color = Color(0xFF10B981),
                    subtitle = "${formatMetres(mosque.distanceMeters)} · heading " +
                        compassLabel(mosque.bearingDeg),
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
): List<CompassMarker> = buildList {
    add(CompassMarker(bearingDeg = 0f, color = Color(0xFFEF4444), label = "North"))
    qiblaBearingDeg?.let {
        add(CompassMarker(bearingDeg = it, color = Color(0xFFF59E0B), label = "Mecca"))
    }
    nearestMosqueBearingDeg?.let { bearing ->
        val distLabel = nearestMosqueDistance?.let { " · ${formatMetres(it)}" }.orEmpty()
        add(CompassMarker(bearingDeg = bearing, color = Color(0xFF10B981), label = "Mosque$distLabel"))
    }
}

@Composable
private fun BearingRow(
    label: String,
    bearingDeg: Float,
    color: Color,
    subtitle: String? = null,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ColoredDot(color)
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
    }
}

@Composable
private fun ColoredDot(color: Color) {
    Canvas(modifier = Modifier.size(12.dp)) {
        drawCircle(color)
    }
}

private fun bearingText(bearingDeg: Float): String {
    val n = ((bearingDeg % 360f) + 360f) % 360f
    return "${compassLabel(n)} · ${n.toInt()}°"
}

private fun formatMetres(m: Double): String =
    if (m < 1000) "${m.toInt()} m" else "%.1f km".format(m / 1000.0)
