package net.omarss.omono.feature.places

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.comparables.shouldBeGreaterThan
import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

// Robolectric needed because TomTomSearchClient.parseResponse uses
// android.org.json, which is a stubbed shim in plain JVM unit tests.
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class TomTomSearchClientTest {

    private val client = TomTomSearchClient(apiKey = "test-key")

    @Test
    fun `parses a two-result response`() {
        // Distilled from a real TomTom nearbySearch response — only
        // the fields we actually read.
        val json = """
            {
              "summary": { "numResults": 2 },
              "results": [
                {
                  "id": "SA/POI/p1/1001",
                  "position": { "lat": 24.7136, "lon": 46.6753 },
                  "poi": { "name": "Row Cafe", "phone": "+966500000000" },
                  "address": { "freeformAddress": "King Fahd Rd, Riyadh" }
                },
                {
                  "id": "SA/POI/p1/1002",
                  "position": { "lat": 24.7200, "lon": 46.6760 },
                  "poi": { "name": "Java Time" },
                  "address": { "freeformAddress": "Olaya St, Riyadh" }
                }
              ]
            }
        """.trimIndent()

        val places = client.parseResponse(
            json = json,
            category = PlaceCategory.COFFEE,
            userLat = 24.7100,
            userLon = 46.6750,
        )
        places shouldHaveSize 2
        places[0].name shouldBe "Row Cafe"
        places[0].category shouldBe PlaceCategory.COFFEE
        places[0].address shouldBe "King Fahd Rd, Riyadh"
        places[0].phone shouldBe "+966500000000"
        // Sorted by distance — Row Cafe is closer to (24.71, 46.675).
        places[0].distanceMeters shouldBeGreaterThan 0.0
        (places[0].distanceMeters < places[1].distanceMeters) shouldBe true
    }

    @Test
    fun `parses empty results`() {
        val json = """{"summary":{"numResults":0},"results":[]}"""
        val places = client.parseResponse(
            json = json,
            category = PlaceCategory.COFFEE,
            userLat = 0.0,
            userLon = 0.0,
        )
        places shouldHaveSize 0
    }

    @Test
    fun `malformed json returns empty`() {
        val places = client.parseResponse(
            json = "not json",
            category = PlaceCategory.COFFEE,
            userLat = 0.0,
            userLon = 0.0,
        )
        places shouldHaveSize 0
    }

    @Test
    fun `haversine north pole to equator is one quarter circumference`() {
        // Earth's meridional quarter-circumference ≈ 10,002 km.
        val meters = haversineMeters(90.0, 0.0, 0.0, 0.0)
        (meters > 9_900_000 && meters < 10_100_000) shouldBe true
    }

    @Test
    fun `bearing due east is 90 degrees`() {
        val bearing = bearingDegrees(0.0, 0.0, 0.0, 1.0)
        (bearing > 89.5f && bearing < 90.5f) shouldBe true
    }

    @Test
    fun `bearing due north is 0 degrees`() {
        val bearing = bearingDegrees(0.0, 0.0, 1.0, 0.0)
        (bearing < 0.5f || bearing > 359.5f) shouldBe true
    }
}
