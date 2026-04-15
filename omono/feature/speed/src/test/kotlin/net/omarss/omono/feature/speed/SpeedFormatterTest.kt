package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import io.kotest.matchers.types.shouldBeInstanceOf
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureState
import org.junit.Test

class SpeedFormatterTest {

    @Test
    fun `below stationary threshold renders as idle`() {
        val state = formatSpeedState(mps = 0.2f, unit = SpeedUnit.KmH)
        state.shouldBeInstanceOf<FeatureState.Idle>()
        state.summary shouldBe "— km/h"
    }

    @Test
    fun `at exactly the threshold is still considered stationary`() {
        val state = formatSpeedState(mps = STATIONARY_THRESHOLD_MPS - 0.01f, unit = SpeedUnit.Mph)
        state.shouldBeInstanceOf<FeatureState.Idle>()
        state.summary shouldBe "— mph"
    }

    @Test
    fun `walking pace renders in km per hour`() {
        // ~5 km/h walking pace = 1.389 m/s
        val state = formatSpeedState(mps = 1.389f, unit = SpeedUnit.KmH)
        state.shouldBeInstanceOf<FeatureState.Active>()
        state.summary shouldBe "5.0 km/h"
    }

    @Test
    fun `cycling speed renders in mph`() {
        // 10 m/s = ~22.37 mph
        val state = formatSpeedState(mps = 10f, unit = SpeedUnit.Mph)
        state.shouldBeInstanceOf<FeatureState.Active>()
        state.summary shouldBe "22.4 mph"
    }

    @Test
    fun `raw m per s passes through unchanged`() {
        val state = formatSpeedState(mps = 12.34f, unit = SpeedUnit.Ms)
        state.summary shouldBe "12.3 m/s"
    }

    @Test
    fun `metadata always carries speed in km per hour`() {
        val state = formatSpeedState(mps = 10f, unit = SpeedUnit.Mph)
        state.shouldBeInstanceOf<FeatureState.Active>()
        val meta = (state as FeatureState.Active).metadata
        // 10 m/s == 36 km/h
        (meta[FeatureState.META_SPEED_KMH] ?: 0.0) shouldBe 36.0
    }

    @Test
    fun `speed limit appears in summary and metadata`() {
        val state = formatSpeedState(mps = 16.67f, unit = SpeedUnit.KmH, limitKmh = 60f)
        state.shouldBeInstanceOf<FeatureState.Active>()
        // 16.67 m/s == 60 km/h, limit 60
        state.summary shouldBe "60.0 km/h (limit 60 km/h)"
        val meta = (state as FeatureState.Active).metadata
        (meta[FeatureState.META_SPEED_LIMIT_KMH] ?: 0.0) shouldBe 60.0
    }

    @Test
    fun `no limit means no suffix`() {
        val state = formatSpeedState(mps = 16.67f, unit = SpeedUnit.KmH, limitKmh = null)
        state.summary shouldBe "60.0 km/h"
        val meta = (state as FeatureState.Active).metadata
        (FeatureState.META_SPEED_LIMIT_KMH in meta) shouldBe false
    }
}
