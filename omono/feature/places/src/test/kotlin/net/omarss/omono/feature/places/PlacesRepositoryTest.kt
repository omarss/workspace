package net.omarss.omono.feature.places

import io.kotest.matchers.collections.shouldContainExactlyInAnyOrder
import io.kotest.matchers.shouldBe
import org.junit.Test

class PlacesRepositoryTest {

    private fun place(name: String, bearing: Float) = Place(
        id = name,
        name = name,
        category = PlaceCategory.COFFEE,
        latitude = 0.0,
        longitude = 0.0,
        distanceMeters = 100.0,
        bearingDegrees = bearing,
        address = null,
        phone = null,
    )

    @Test
    fun `cone 180 keeps everything`() {
        val input = listOf(place("a", 0f), place("b", 90f), place("c", 180f), place("d", 270f))
        filterByDirection(input, heading = 0f, coneDegrees = 180f) shouldBe input
    }

    @Test
    fun `cone 60 keeps only forward places`() {
        val input = listOf(
            place("north", 0f),
            place("east", 90f),
            place("south", 180f),
            place("west", 270f),
            place("nne", 30f),
            place("nnw", 330f),
        )
        val filtered = filterByDirection(input, heading = 0f, coneDegrees = 60f)
        filtered.map { it.name } shouldContainExactlyInAnyOrder listOf("north", "nne", "nnw")
    }

    @Test
    fun `cone wraps across 0`() {
        // Facing north-west (heading 350); a place due north (0) is
        // only 10 degrees off, so a 30-degree cone keeps it.
        val input = listOf(place("due-north", 0f))
        val filtered = filterByDirection(input, heading = 350f, coneDegrees = 30f)
        filtered.size shouldBe 1
    }

    @Test
    fun `low pass smooths across 0 without jumping`() {
        // 358° → 2° is really only 4° of travel; the smoothed result
        // should land somewhere between, not at ~180°.
        val smoothed = circularLowPass(previous = 358f, current = 2f, alpha = 0.5f)
        (smoothed < 10f || smoothed > 350f) shouldBe true
    }
}
