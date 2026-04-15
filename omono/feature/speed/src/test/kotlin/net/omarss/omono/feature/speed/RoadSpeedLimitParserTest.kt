package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import org.junit.Test

class RoadSpeedLimitParserTest {

    private val repo = RoadSpeedLimitRepository()

    @Test
    fun `parses bare integer maxspeed as km per hour`() {
        val json = """{"elements":[{"tags":{"highway":"primary","maxspeed":"60"}}]}"""
        repo.parseMaxSpeed(json) shouldBe 60f
    }

    @Test
    fun `parses mph suffix and converts to km per hour`() {
        val json = """{"elements":[{"tags":{"maxspeed":"35 mph"}}]}"""
        // 35 * 1.609344 ≈ 56.327
        val result = repo.parseMaxSpeed(json) ?: 0f
        (kotlin.math.abs(result - 56.327f) < 0.01f) shouldBe true
    }

    @Test
    fun `qualitative values like walk return null`() {
        val json = """{"elements":[{"tags":{"maxspeed":"walk"}}]}"""
        repo.parseMaxSpeed(json) shouldBe null
    }

    @Test
    fun `none returns null`() {
        val json = """{"elements":[{"tags":{"maxspeed":"none"}}]}"""
        repo.parseMaxSpeed(json) shouldBe null
    }

    @Test
    fun `zero is treated as no limit`() {
        val json = """{"elements":[{"tags":{"maxspeed":"0"}}]}"""
        repo.parseMaxSpeed(json) shouldBe null
    }

    @Test
    fun `missing tag returns null`() {
        val json = """{"elements":[]}"""
        repo.parseMaxSpeed(json) shouldBe null
    }

    @Test
    fun `decimal km per hour values are honoured`() {
        val json = """{"elements":[{"tags":{"maxspeed":"42.5"}}]}"""
        repo.parseMaxSpeed(json) shouldBe 42.5f
    }
}
