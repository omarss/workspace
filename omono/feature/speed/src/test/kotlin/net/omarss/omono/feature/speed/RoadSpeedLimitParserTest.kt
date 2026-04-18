package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import org.junit.Test
import kotlin.math.abs

// Tests for the offline speed-limit selector. The production code
// deserialises from assets/riyadh_speed_limits.json; these tests
// assemble the same in-memory Way objects directly so no Android
// runtime (or Robolectric) is needed.
class RoadSpeedLimitParserTest {

    // --- selectBestLimit: scoring over a set of ways -----------------

    @Test
    fun `empty way list returns null`() {
        selectBestLimit(emptyArray(), 24.7, 46.7, null) shouldBe null
    }

    @Test
    fun `single way directly underfoot returns its maxspeed`() {
        val ways = arrayOf(
            way(maxSpeed = 80f, points = listOf(24.7000 to 46.6990, 24.7000 to 46.7010)),
        )
        selectBestLimit(ways, 24.7000, 46.7000, null) shouldBe 80f
    }

    // At a perpendicular crossing with the user exactly at the junction,
    // heading alone decides which road they're on.
    @Test
    fun `heading aligned with east-west way picks that way over north-south way`() {
        val ways = arrayOf(
            way(maxSpeed = 50f, points = listOf(24.7000 to 46.6990, 24.7000 to 46.7010)),
            way(maxSpeed = 80f, points = listOf(24.6990 to 46.7000, 24.7010 to 46.7000)),
        )
        // Heading 90° (east) → pick the east-west way → 50 km/h.
        selectBestLimit(ways, 24.7000, 46.7000, userBearingDeg = 90f) shouldBe 50f
    }

    @Test
    fun `heading aligned with north-south way picks that way over east-west way`() {
        val ways = arrayOf(
            way(maxSpeed = 50f, points = listOf(24.7000 to 46.6990, 24.7000 to 46.7010)),
            way(maxSpeed = 80f, points = listOf(24.6990 to 46.7000, 24.7010 to 46.7000)),
        )
        selectBestLimit(ways, 24.7000, 46.7000, userBearingDeg = 0f) shouldBe 80f
    }

    // Opposite sense along the same road must still count as aligned —
    // OSM way direction is arbitrary for bidirectional roads.
    @Test
    fun `heading opposite to way direction still counts as aligned`() {
        val ways = arrayOf(
            way(maxSpeed = 50f, points = listOf(24.7000 to 46.6990, 24.7000 to 46.7010)),
            way(maxSpeed = 80f, points = listOf(24.6990 to 46.7000, 24.7010 to 46.7000)),
        )
        // Heading 270° (west) — reverse of the way's encoded east direction.
        selectBestLimit(ways, 24.7000, 46.7000, userBearingDeg = 270f) shouldBe 50f
    }

    // Closer road wins by a comfortable margin when heading is absent,
    // even if a farther candidate exists.
    @Test
    fun `closer way wins when no heading is given`() {
        val ways = arrayOf(
            way(maxSpeed = 40f, points = listOf(24.70001 to 46.6990, 24.70001 to 46.7010)),
            way(maxSpeed = 100f, points = listOf(24.70020 to 46.6990, 24.70020 to 46.7010)),
        )
        selectBestLimit(ways, 24.7000, 46.7000, null) shouldBe 40f
    }

    // Way is far enough outside the bbox pre-filter that the scorer
    // never even considers it — ensures the pre-filter doesn't reject
    // ways that genuinely pass through the user's neighbourhood, but
    // also doesn't let distant ways dominate.
    @Test
    fun `way far outside the search square is skipped`() {
        val ways = arrayOf(
            way(maxSpeed = 60f, points = listOf(24.8000 to 46.7000, 24.8010 to 46.7010)),
        )
        selectBestLimit(ways, 24.7000, 46.7000, null) shouldBe null
    }

    // --- Geodesy helper sanity ---------------------------------------

    @Test
    fun `bearing due east is 90 degrees`() {
        val b = bearingDeg(24.7, 46.7, 24.7, 46.71)
        (abs(b - 90.0) < 0.5) shouldBe true
    }

    @Test
    fun `bearing due north is 0 degrees`() {
        val b = bearingDeg(24.7, 46.7, 24.71, 46.7)
        (abs(b) < 0.5) shouldBe true
    }

    @Test
    fun `angular diff wraps around 360`() {
        angularDiffDeg(10.0, 350.0) shouldBe 20.0
        angularDiffDeg(359.0, 1.0) shouldBe 2.0
        angularDiffDeg(180.0, 0.0) shouldBe 180.0
    }

    @Test
    fun `distance to segment is zero on the line`() {
        val d = distanceToSegmentMeters(24.7000, 46.7000, 24.6999, 46.7000, 24.7001, 46.7000)
        (d < 0.5) shouldBe true
    }

    @Test
    fun `distance to perpendicular point is horizontal offset`() {
        val d = distanceToSegmentMeters(24.7000, 46.7001, 24.6999, 46.7000, 24.7001, 46.7000)
        // 0.0001° lon × 111320 × cos(24.7°) ≈ 10.1 m
        (abs(d - 10.1) < 0.5) shouldBe true
    }

    // --- fixtures -----------------------------------------------------

    private fun way(
        maxSpeed: Float,
        points: List<Pair<Double, Double>>,
    ): RoadSpeedLimitRepository.Way {
        val lats = FloatArray(points.size) { points[it].first.toFloat() }
        val lons = FloatArray(points.size) { points[it].second.toFloat() }
        return RoadSpeedLimitRepository.Way(
            maxSpeedKmh = maxSpeed,
            lats = lats,
            lons = lons,
            minLat = lats.min(),
            maxLat = lats.max(),
            minLon = lons.min(),
            maxLon = lons.max(),
        )
    }
}
