package net.omarss.omono.ui.places

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.cos
import kotlin.math.sin

// A marker to overlay on the compass ring — "this is which direction
// X lies in". The bearing is in true degrees from north (0 = north,
// 90 = east); the rose itself rotates it onto the screen based on
// the current device heading.
data class CompassMarker(
    val bearingDeg: Float,
    val color: Color,
    val label: String,
)

// Circular compass dial that shows:
//   - A fixed centre arrow pointing up (= device forward).
//   - Cardinal labels (N / E / S / W) positioned on the ring, rotated
//     against the device heading so N always points to true north.
//   - One coloured dot + short label per CompassMarker, positioned
//     the same way. Designed for up to ~5 markers before the ring
//     starts feeling crowded.
//   - A heading badge at the bottom: "NE · 42°" so the user can read
//     the exact direction without eyeballing the arrow.
//
// Dial is drawn entirely in a single Canvas pass (ticks, ring,
// arrow), with labels layered on top as Text composables so the type
// renders with the user's accessibility scale.
@Composable
fun CompassRose(
    headingDeg: Float,
    markers: List<CompassMarker>,
    modifier: Modifier = Modifier,
) {
    val density = LocalDensity.current
    val ringColor = MaterialTheme.colorScheme.outlineVariant
    val tickColor = MaterialTheme.colorScheme.outline
    val cardinalTickColor = MaterialTheme.colorScheme.onSurfaceVariant
    val arrowColor = MaterialTheme.colorScheme.primary

    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier.size(200.dp),
            contentAlignment = Alignment.Center,
        ) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val centre = Offset(size.width / 2f, size.height / 2f)
                val outerRadius = size.minDimension / 2f - with(density) { 16.dp.toPx() }
                val innerRingRadius = outerRadius - with(density) { 6.dp.toPx() }

                // Ring
                drawCircle(
                    color = ringColor,
                    radius = outerRadius,
                    center = centre,
                    style = Stroke(width = with(density) { 1.5.dp.toPx() }),
                )

                // Tick marks every 15°, taller at cardinals. Everything
                // rotates by -headingDeg so N stays pointed at north.
                rotate(-headingDeg, pivot = centre) {
                    for (deg in 0 until 360 step 15) {
                        val isCardinal = deg % 90 == 0
                        val isIntercardinal = deg % 45 == 0 && !isCardinal
                        val tickLen = with(density) {
                            when {
                                isCardinal -> 14.dp.toPx()
                                isIntercardinal -> 8.dp.toPx()
                                else -> 4.dp.toPx()
                            }
                        }
                        val rad = Math.toRadians(deg.toDouble() - 90.0)
                        val cx = cos(rad).toFloat()
                        val cy = sin(rad).toFloat()
                        val outer = Offset(
                            centre.x + innerRingRadius * cx,
                            centre.y + innerRingRadius * cy,
                        )
                        val inner = Offset(
                            centre.x + (innerRingRadius - tickLen) * cx,
                            centre.y + (innerRingRadius - tickLen) * cy,
                        )
                        drawLine(
                            color = if (isCardinal) cardinalTickColor else tickColor,
                            start = inner,
                            end = outer,
                            strokeWidth = with(density) {
                                if (isCardinal) 2.5.dp.toPx() else 1.dp.toPx()
                            },
                        )
                    }

                    // Coloured dots for each marker on the ring.
                    markers.forEach { marker ->
                        val rad = Math.toRadians(marker.bearingDeg.toDouble() - 90.0)
                        val pos = Offset(
                            centre.x + innerRingRadius * cos(rad).toFloat(),
                            centre.y + innerRingRadius * sin(rad).toFloat(),
                        )
                        drawCircle(
                            color = marker.color,
                            radius = with(density) { 6.dp.toPx() },
                            center = pos,
                        )
                    }
                }

                // Centre arrow — fixed, always up. This is the "you
                // are facing this way" indicator; everything else on
                // the dial rotates around it.
                val arrowTip = Offset(
                    centre.x,
                    centre.y - outerRadius + with(density) { 18.dp.toPx() },
                )
                val arrowBase = Offset(
                    centre.x,
                    centre.y + with(density) { 14.dp.toPx() },
                )
                drawLine(
                    color = arrowColor,
                    start = arrowBase,
                    end = arrowTip,
                    strokeWidth = with(density) { 3.dp.toPx() },
                )
                // Arrowhead
                val headWidth = with(density) { 8.dp.toPx() }
                val headLen = with(density) { 12.dp.toPx() }
                val head = Path().apply {
                    moveTo(arrowTip.x, arrowTip.y)
                    lineTo(arrowTip.x - headWidth, arrowTip.y + headLen)
                    lineTo(arrowTip.x + headWidth, arrowTip.y + headLen)
                    close()
                }
                drawPath(path = head, color = arrowColor)
            }

            // Cardinal-letter labels, positioned with Modifier.offset
            // so they render crisp at the user's accessibility scale.
            // The ring rotates visually via tick marks; the labels move
            // around the circle by bearing.
            CardinalLabels(headingDeg = headingDeg)
        }

        Spacer(Modifier.height(10.dp))

        val heading = ((headingDeg % 360f) + 360f) % 360f
        Text(
            text = "${compassLabel(headingDeg)} · ${heading.toInt()}°",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )

        if (markers.isNotEmpty()) {
            Spacer(Modifier.height(4.dp))
            MarkerLegend(markers)
        }
    }
}

@Composable
private fun CardinalLabels(headingDeg: Float) {
    val density = LocalDensity.current
    // Radius at which the N/E/S/W letters sit — slightly inside the
    // ring so the tick marks stay visible.
    val r = with(density) { 76.dp.toPx() }
    val cardinals = listOf("N" to 0f, "E" to 90f, "S" to 180f, "W" to 270f)
    cardinals.forEach { (text, bearing) ->
        val onScreenDeg = bearing - headingDeg
        val rad = Math.toRadians(onScreenDeg.toDouble() - 90.0)
        val xPx = (r * cos(rad)).toFloat()
        val yPx = (r * sin(rad)).toFloat()
        with(density) {
            Text(
                text = text,
                modifier = Modifier.offsetPx(xPx, yPx),
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                color = if (text == "N") {
                    Color(0xFFEF4444) // red — true north
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
                fontSize = 14.sp,
            )
        }
    }
}

// Colour-coded key row underneath the dial so the user knows what
// each dot on the ring represents. Compact chips, one per marker.
@Composable
private fun MarkerLegend(markers: List<CompassMarker>) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally),
    ) {
        markers.forEach { marker ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .padding(0.dp)
                        .let { it },
                ) {
                    Canvas(modifier = Modifier.fillMaxSize()) {
                        drawCircle(color = marker.color)
                    }
                }
                Spacer(Modifier.size(4.dp))
                Text(
                    text = marker.label,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

// Pixel offset (x, y) from the Box centre. The parent Box uses
// contentAlignment = Center, so `.offset { ... }` shifts each label
// away from centre by the polar-computed delta.
private fun Modifier.offsetPx(xPx: Float, yPx: Float): Modifier =
    this.offset { androidx.compose.ui.unit.IntOffset(xPx.toInt(), yPx.toInt()) }
