package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import kotlin.math.abs

// Robolectric provides the org.json stubs that Overpass response parsing
// relies on. SDK 34 is the project-wide default for test shadows.
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class RoadSpeedLimitParserTest {

    private val repo = RoadSpeedLimitRepository()

    // --- parseMaxSpeedValue: tag-value scalar parsing -----------------

    @Test
    fun `parses bare integer as km per hour`() {
        repo.parseMaxSpeedValue("60") shouldBe 60f
    }

    @Test
    fun `parses mph suffix and converts to km per hour`() {
        val result = repo.parseMaxSpeedValue("35 mph") ?: 0f
        (abs(result - 56.327f) < 0.01f) shouldBe true
    }

    @Test
    fun `qualitative values like walk return null`() {
        repo.parseMaxSpeedValue("walk") shouldBe null
    }

    @Test
    fun `none returns null`() {
        repo.parseMaxSpeedValue("none") shouldBe null
    }

    @Test
    fun `zero is treated as no limit`() {
        repo.parseMaxSpeedValue("0") shouldBe null
    }

    @Test
    fun `empty value returns null`() {
        repo.parseMaxSpeedValue("") shouldBe null
    }

    @Test
    fun `decimal km per hour values are honoured`() {
        repo.parseMaxSpeedValue("42.5") shouldBe 42.5f
    }

    // --- selectBestLimit: full response scoring -----------------------

    @Test
    fun `empty element list returns null`() {
        val json = """{"elements":[]}"""
        repo.selectBestLimit(json, 24.7, 46.7, null) shouldBe null
    }

    @Test
    fun `way without geometry still returns its maxspeed`() {
        val json = """{"elements":[{"type":"way","tags":{"highway":"primary","maxspeed":"60"}}]}"""
        repo.selectBestLimit(json, 24.7, 46.7, null) shouldBe 60f
    }

    @Test
    fun `single way with geometry returns its maxspeed`() {
        val json = wayJson(maxspeed = "80", geometry = listOf(24.7000 to 46.6990, 24.7000 to 46.7010))
        val wrapped = """{"elements":[$json]}"""
        repo.selectBestLimit(wrapped, 24.7000, 46.7000, null) shouldBe 80f
    }

    // At a perpendicular crossing with the user exactly at the junction,
    // heading alone decides which road they're on.
    @Test
    fun `heading aligned with east-west way picks that way over north-south way`() {
        val eastWest = wayJson(maxspeed = "50", geometry = listOf(24.7000 to 46.6990, 24.7000 to 46.7010))
        val northSouth = wayJson(maxspeed = "80", geometry = listOf(24.6990 to 46.7000, 24.7010 to 46.7000))
        val wrapped = """{"elements":[$eastWest,$northSouth]}"""
        // Heading 90° (east) → pick east-west way → 50 km/h.
        repo.selectBestLimit(wrapped, 24.7000, 46.7000, userBearingDeg = 90f) shouldBe 50f
    }

    @Test
    fun `heading aligned with north-south way picks that way over east-west way`() {
        val eastWest = wayJson(maxspeed = "50", geometry = listOf(24.7000 to 46.6990, 24.7000 to 46.7010))
        val northSouth = wayJson(maxspeed = "80", geometry = listOf(24.6990 to 46.7000, 24.7010 to 46.7000))
        val wrapped = """{"elements":[$eastWest,$northSouth]}"""
        repo.selectBestLimit(wrapped, 24.7000, 46.7000, userBearingDeg = 0f) shouldBe 80f
    }

    // Opposite sense along the same road must still count as aligned —
    // OSM way direction is arbitrary for bidirectional roads.
    @Test
    fun `heading opposite to way direction still counts as aligned`() {
        val eastWest = wayJson(maxspeed = "50", geometry = listOf(24.7000 to 46.6990, 24.7000 to 46.7010))
        val northSouth = wayJson(maxspeed = "80", geometry = listOf(24.6990 to 46.7000, 24.7010 to 46.7000))
        val wrapped = """{"elements":[$eastWest,$northSouth]}"""
        // Heading 270° (west) — reverse of the way's encoded east direction.
        repo.selectBestLimit(wrapped, 24.7000, 46.7000, userBearingDeg = 270f) shouldBe 50f
    }

    // Closer road wins by a comfortable margin when heading is absent,
    // even if a farther candidate exists.
    @Test
    fun `closer way wins when no heading is given`() {
        val near = wayJson(maxspeed = "40", geometry = listOf(24.70001 to 46.6990, 24.70001 to 46.7010))
        val far = wayJson(maxspeed = "100", geometry = listOf(24.70020 to 46.6990, 24.70020 to 46.7010))
        val wrapped = """{"elements":[$near,$far]}"""
        repo.selectBestLimit(wrapped, 24.7000, 46.7000, null) shouldBe 40f
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
        // Point exactly at the midpoint of a segment.
        val d = distanceToSegmentMeters(24.7000, 46.7000, 24.6999, 46.7000, 24.7001, 46.7000)
        (d < 0.5) shouldBe true
    }

    @Test
    fun `distance to perpendicular point is horizontal offset`() {
        // Segment runs N-S at lon=46.7000. Point 0.0001° east ~= 10m at lat 24.7.
        val d = distanceToSegmentMeters(24.7000, 46.7001, 24.6999, 46.7000, 24.7001, 46.7000)
        // 0.0001° lon * 111320 * cos(24.7°) ≈ 10.1 m
        (abs(d - 10.1) < 0.5) shouldBe true
    }

    // --- fixtures -----------------------------------------------------

    private fun wayJson(maxspeed: String, geometry: List<Pair<Double, Double>>): String {
        val geom = geometry.joinToString(",") { (lat, lon) -> """{"lat":$lat,"lon":$lon}""" }
        return """{"type":"way","tags":{"highway":"primary","maxspeed":"$maxspeed"},"geometry":[$geom]}"""
    }
}
