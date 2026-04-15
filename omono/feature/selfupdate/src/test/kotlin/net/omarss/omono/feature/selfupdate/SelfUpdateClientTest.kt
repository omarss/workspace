package net.omarss.omono.feature.selfupdate

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SelfUpdateClientTest {

    private val client = SelfUpdateClient()

    @Test
    fun `parses manifest with multiple releases`() {
        val json = """
        {
          "generated_at": "2026-04-15T19:43:34Z",
          "apps": {
            "omono": {
              "releases": [
                {
                  "version": "0.9.0",
                  "apk": "omono.0.9.0.apk",
                  "released_at": "2026-04-15T19:43:34Z",
                  "size_bytes": 14156132,
                  "sha256": "abc",
                  "changelog": ["feat: a", "feat: b"]
                },
                {
                  "version": "0.8.0",
                  "apk": "omono.0.8.0.apk",
                  "released_at": "2026-04-15T19:29:41Z",
                  "size_bytes": 14156132,
                  "sha256": "def",
                  "changelog": ["fix: c"]
                }
              ]
            }
          }
        }
        """.trimIndent()

        val releases = client.parseReleases(json, "omono")
        releases shouldHaveSize 2
        releases[0].version shouldBe "0.9.0"
        releases[0].apkFileName shouldBe "omono.0.9.0.apk"
        releases[0].changelog shouldBe listOf("feat: a", "feat: b")
        releases[0].sha256 shouldBe "abc"
        releases[1].version shouldBe "0.8.0"
    }

    @Test
    fun `returns empty list for unknown app`() {
        val json = """{"apps":{"omono":{"releases":[]}}}"""
        client.parseReleases(json, "other") shouldBe emptyList()
    }

    @Test
    fun `tolerates malformed json`() {
        client.parseReleases("not-json", "omono") shouldBe emptyList()
    }

    @Test
    fun `skips release entries missing version or apk`() {
        val json = """
        {
          "apps": {
            "omono": {
              "releases": [
                {"version": "1.0.0", "apk": "omono.1.0.0.apk"},
                {"version": "", "apk": "omono.broken.apk"},
                {"version": "0.9.0"}
              ]
            }
          }
        }
        """.trimIndent()
        val releases = client.parseReleases(json, "omono")
        releases shouldHaveSize 1
        releases[0].version shouldBe "1.0.0"
    }

    @Test
    fun `apkUrl prefixes base url`() {
        client.apkUrl("omono.0.9.0.apk") shouldBe "https://apps.omarss.net/omono.0.9.0.apk"
    }
}
