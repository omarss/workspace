package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import org.junit.Test

// Covers the pure filterSpeed helper that gates `location.speed` before
// it reaches the notification / trip recorder / traffic watcher.
class SpeedFilterTest {

    @Test
    fun `no speed reading returns zero regardless of other fields`() {
        filterSpeed(
            hasSpeed = false,
            rawSpeedMps = 50f,
            hasAccuracy = true,
            accuracyMeters = 4f,
            hasSpeedAccuracy = true,
            speedAccuracyMps = 0.5f,
        ) shouldBe 0f
    }

    @Test
    fun `zero reading passes through even when noisy`() {
        // Provider correctly reports 0 m/s — trust it, don't second-guess.
        filterSpeed(
            hasSpeed = true,
            rawSpeedMps = 0f,
            hasAccuracy = true,
            accuracyMeters = 100f,
            hasSpeedAccuracy = false,
            speedAccuracyMps = Float.NaN,
        ) shouldBe 0f
    }

    @Test
    fun `confident high-accuracy speed passes through`() {
        filterSpeed(
            hasSpeed = true,
            rawSpeedMps = 27f, // ~97 km/h
            hasAccuracy = true,
            accuracyMeters = 4f,
            hasSpeedAccuracy = true,
            speedAccuracyMps = 0.6f,
        ) shouldBe 27f
    }

    @Test
    fun `high speed accuracy uncertainty is dropped to zero`() {
        // Classic parked-car ghost: provider reports 32 m/s (~118 km/h)
        // but with a ±15 m/s uncertainty. Must read as stationary.
        filterSpeed(
            hasSpeed = true,
            rawSpeedMps = 32f,
            hasAccuracy = true,
            accuracyMeters = 35f,
            hasSpeedAccuracy = true,
            speedAccuracyMps = 15f,
        ) shouldBe 0f
    }

    @Test
    fun `speed accuracy at the boundary is trusted`() {
        filterSpeed(
            hasSpeed = true,
            rawSpeedMps = 10f,
            hasAccuracy = true,
            accuracyMeters = 5f,
            hasSpeedAccuracy = true,
            speedAccuracyMps = SPEED_ACCURACY_MAX_MPS,
        ) shouldBe 10f
    }

    @Test
    fun `no speed accuracy falls back to position accuracy gate`() {
        // Pre-API-26 or poor-quality device — only position accuracy
        // available. 4 m halo is tight enough, keep the reading.
        filterSpeed(
            hasSpeed = true,
            rawSpeedMps = 8f,
            hasAccuracy = true,
            accuracyMeters = 4f,
            hasSpeedAccuracy = false,
            speedAccuracyMps = Float.NaN,
        ) shouldBe 8f
    }

    @Test
    fun `loose position accuracy without speed accuracy is dropped`() {
        filterSpeed(
            hasSpeed = true,
            rawSpeedMps = 8f,
            hasAccuracy = true,
            accuracyMeters = 75f,
            hasSpeedAccuracy = false,
            speedAccuracyMps = Float.NaN,
        ) shouldBe 0f
    }

    @Test
    fun `no accuracy at all defaults to distrust`() {
        filterSpeed(
            hasSpeed = true,
            rawSpeedMps = 8f,
            hasAccuracy = false,
            accuracyMeters = Float.NaN,
            hasSpeedAccuracy = false,
            speedAccuracyMps = Float.NaN,
        ) shouldBe 0f
    }
}
