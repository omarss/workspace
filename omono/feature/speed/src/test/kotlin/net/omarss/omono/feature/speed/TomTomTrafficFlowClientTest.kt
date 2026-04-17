package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

// org.json is an Android stub on the JVM; Robolectric brings it in.
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class TomTomTrafficFlowClientTest {

    private val client = TomTomTrafficFlowClient(apiKey = "test-key")

    @Test
    fun `parses a typical flow response`() {
        val json = """{
          "flowSegmentData": {
            "frc": "FRC3",
            "currentSpeed": 32,
            "freeFlowSpeed": 56,
            "confidence": 0.8,
            "roadClosure": false
          }
        }""".trimIndent()
        val sample = client.parseResponse(json)!!
        sample.currentSpeedKmh shouldBe 32f
        sample.freeFlowSpeedKmh shouldBe 56f
        sample.confidence shouldBe 0.8f
        sample.roadClosure shouldBe false
    }

    @Test
    fun `parses road closure flag`() {
        val json = """{
          "flowSegmentData": {
            "currentSpeed": 0,
            "freeFlowSpeed": 80,
            "confidence": 0.5,
            "roadClosure": true
          }
        }""".trimIndent()
        client.parseResponse(json)!!.roadClosure shouldBe true
    }

    @Test
    fun `returns null when freeFlowSpeed is zero`() {
        val json = """{"flowSegmentData":{"currentSpeed":0,"freeFlowSpeed":0}}"""
        client.parseResponse(json) shouldBe null
    }

    @Test
    fun `returns null on malformed JSON`() {
        client.parseResponse("not json at all") shouldBe null
    }

    @Test
    fun `returns null when flowSegmentData is missing`() {
        client.parseResponse("""{"other":1}""") shouldBe null
    }

    @Test
    fun `reports not configured when api key is blank`() {
        val unconfigured = TomTomTrafficFlowClient(apiKey = "")
        unconfigured.isConfigured shouldBe false
    }
}
