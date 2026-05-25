package net.omarss.omono.feature.twitter

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.nulls.shouldNotBeNull
import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

// Robolectric is needed because the Android-bundled `org.json` is a
// throw-stub on the JVM test classpath; running through Robolectric
// provides the real implementation so the parser can be exercised.
@RunWith(RobolectricTestRunner::class)
class TweetsClientParseTest {

    // Drives the client's pure parse() against a real wire shape — same
    // body the Go service emits today (captured by curl during local
    // smoke). If either side drifts, this catches it before the app
    // ever connects to the live service.
    private val ksaWire = """
        {
          "country": "ksa",
          "generated_at": "2026-05-25T13:00:00Z",
          "tweets": [
            {
              "id": "ksa-1",
              "author": "وزارة الداخلية",
              "handle": "MOISaudiArabia",
              "text": "تم تشغيل خدمة جديدة لتجديد الإقامة من خلال تطبيق أبشر.",
              "created_at": "2026-05-25T12:40:00Z",
              "lang": "ar",
              "place": "Riyadh, SA",
              "country": "ksa",
              "reply_count": 142,
              "like_count": 2103,
              "retweet_count": 587,
              "spam_score": 0
            },
            {
              "id": "ksa-2",
              "author": "Saudi Arabia",
              "handle": "Saudi_Gazette",
              "text": "NEOM unveils first all-electric coastal city section.",
              "created_at": "2026-05-25T12:15:00Z",
              "lang": "en",
              "place": "Tabuk, SA",
              "country": "ksa",
              "reply_count": 28,
              "like_count": 340,
              "retweet_count": 95,
              "spam_score": 0
            }
          ]
        }
    """.trimIndent()

    private fun newClient() = TweetsClient(baseUrl = "https://tweets.omarss.net")

    @Test
    fun `parses every tweet from a well-formed payload`() {
        val parsed = newClient().parse(ksaWire)
        parsed shouldHaveSize 2

        val first = parsed[0]
        first.id shouldBe "ksa-1"
        first.handle shouldBe "MOISaudiArabia"
        first.country shouldBe Country.KSA
        first.place shouldBe "Riyadh, SA"
        first.likeCount shouldBe 2103
        first.spamScore shouldBe 0f
        // Arabic body must survive UTF-8 round-trip unchanged.
        first.text.contains("أبشر") shouldBe true
    }

    @Test
    fun `unknown country code drops the tweet rather than crashing`() {
        // First tweet has an unrecognised country → dropped; second still
        // has the literal "ksa" so it survives. Defensive parser.
        val payload = """
            {"country":"ksa","generated_at":"2026-05-25T13:00:00Z","tweets":[
              {"id":"bad-1","author":"x","handle":"x","text":"will be dropped","created_at":"2026-05-25T12:00:00Z","country":"zz"},
              {"id":"good-1","author":"y","handle":"y","text":"survives","created_at":"2026-05-25T12:00:00Z","country":"ksa"}
            ]}
        """.trimIndent()
        val parsed = newClient().parse(payload)
        parsed shouldHaveSize 1
        parsed[0].id shouldBe "good-1"
    }

    @Test
    fun `missing optional fields default safely`() {
        val payload = """
            {"country":"eg","generated_at":"2026-05-25T13:00:00Z","tweets":[
              {"id":"eg-1","author":"","handle":"","text":"hello","created_at":"2026-05-25T12:00:00Z","country":"eg"}
            ]}
        """.trimIndent()
        val parsed = newClient().parse(payload)
        val only = parsed.firstOrNull()
        only.shouldNotBeNull()
        only.lang shouldBe null
        only.place shouldBe null
        only.likeCount shouldBe 0
        only.spamScore shouldBe 0f
    }

    @Test
    fun `garbage payload returns empty list`() {
        newClient().parse("not json at all") shouldHaveSize 0
        newClient().parse("") shouldHaveSize 0
        newClient().parse("{\"tweets\":\"not an array\"}") shouldHaveSize 0
    }

    @Test
    fun `is not configured when base url is blank`() {
        TweetsClient(baseUrl = "").isConfigured shouldBe false
        TweetsClient(baseUrl = "https://tweets.omarss.net").isConfigured shouldBe true
    }

    @Test
    fun `country roundtrip via fromCode`() {
        Country.fromCode("ksa") shouldBe Country.KSA
        Country.fromCode("eg") shouldBe Country.Egypt
        Country.fromCode("zz") shouldBe null
        Country.fromCode(null) shouldBe null
    }
}
