package net.omarss.omono.feature.places

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

// Parser drives org.json, which is an Android-stub on plain JVM —
// Robolectric provides the real implementation.
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class GPlacesClientTest {

    private val client = GPlacesClient(
        baseUrl = "https://api-places.omarss.net",
        apiKey = "test-key",
    )

    @Test
    fun `parses a two-result response`() {
        // Shape pinned in gplaces_parser/FEEDBACK.md — any drift here
        // or there without updating both sides will break the client.
        val json = """
            {
              "results": [
                {
                  "id": "ChIJrow-1",
                  "name": "Row Cafe",
                  "name_ar": "مقهى رو",
                  "category": "coffee",
                  "lat": 24.7136,
                  "lon": 46.6753,
                  "address": "King Fahd Rd, Riyadh",
                  "phone": "+966500000000",
                  "rating": 4.6,
                  "review_count": 1832
                },
                {
                  "id": "ChIJjavatime-2",
                  "name": "Java Time",
                  "category": "coffee",
                  "lat": 24.7200,
                  "lon": 46.6760,
                  "address": "Olaya St, Riyadh"
                }
              ],
              "source": "gplaces",
              "generated_at": "2026-04-17T14:58:10Z"
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
        places[0].id shouldBe "ChIJrow-1"
        places[0].address shouldBe "King Fahd Rd, Riyadh"
        places[0].phone shouldBe "+966500000000"
        places[0].category shouldBe PlaceCategory.COFFEE
        // Sorted ascending by distance (Row Cafe is closer).
        (places[0].distanceMeters < places[1].distanceMeters) shouldBe true
        // Java Time has no phone in the payload — must tolerate the
        // missing field and leave phone null, not crash.
        places[1].phone shouldBe null
    }

    @Test
    fun `empty results list returns empty`() {
        val json = """{"results": [], "source": "gplaces"}"""
        val places = client.parseResponse(
            json = json,
            category = PlaceCategory.BANK,
            userLat = 0.0,
            userLon = 0.0,
        )
        places shouldHaveSize 0
    }

    @Test
    fun `result missing lat or lon is skipped`() {
        val json = """
            {
              "results": [
                {"id":"ok","name":"Ok","lat":24.7,"lon":46.7},
                {"id":"no-lat","name":"Missing Lat","lon":46.7},
                {"id":"no-lon","name":"Missing Lon","lat":24.7}
              ]
            }
        """.trimIndent()
        val places = client.parseResponse(
            json = json,
            category = PlaceCategory.COFFEE,
            userLat = 24.7, userLon = 46.7,
        )
        places shouldHaveSize 1
        places[0].id shouldBe "ok"
    }

    @Test
    fun `result missing id or name is skipped`() {
        val json = """
            {
              "results": [
                {"id":"","name":"No id","lat":24.7,"lon":46.7},
                {"id":"ok","name":"","lat":24.7,"lon":46.7},
                {"id":"good","name":"Good","lat":24.7,"lon":46.7}
              ]
            }
        """.trimIndent()
        val places = client.parseResponse(
            json = json,
            category = PlaceCategory.COFFEE,
            userLat = 24.7, userLon = 46.7,
        )
        places shouldHaveSize 1
        places[0].name shouldBe "Good"
    }

    @Test
    fun `malformed json returns empty`() {
        client.parseResponse(
            json = "not json",
            category = PlaceCategory.COFFEE,
            userLat = 0.0,
            userLon = 0.0,
        ) shouldHaveSize 0
    }

    @Test
    fun `missing api key or url reports not configured`() {
        GPlacesClient(baseUrl = "", apiKey = "k").isConfigured shouldBe false
        GPlacesClient(baseUrl = "https://x", apiKey = "").isConfigured shouldBe false
        GPlacesClient(baseUrl = "https://x", apiKey = "k").isConfigured shouldBe true
    }

    @Test
    fun `category slugs match the FEEDBACK contract`() {
        // Server-side FEEDBACK.md lists these exact slugs. Renaming
        // here without updating there will produce 400s.
        PlaceCategory.COFFEE.slug shouldBe "coffee"
        PlaceCategory.RESTAURANT.slug shouldBe "restaurant"
        PlaceCategory.FAST_FOOD.slug shouldBe "fast_food"
        PlaceCategory.EV_CHARGER.slug shouldBe "ev_charger"
        PlaceCategory.POST_OFFICE.slug shouldBe "post_office"
    }
}
