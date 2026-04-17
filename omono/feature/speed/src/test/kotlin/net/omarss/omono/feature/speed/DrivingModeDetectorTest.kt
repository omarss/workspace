package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import org.junit.Test

class DrivingModeDetectorTest {

    // Convenience: step the detector from t=0 with a sequence of
    // (speed_mps, delta_ms) pairs and return the final isDriving.
    private fun run(vararg samples: Pair<Float, Long>): Boolean {
        val detector = DrivingModeDetector()
        var t = 0L
        for ((speed, delta) in samples) {
            t += delta
            detector.onSample(speed, t)
        }
        return detector.isDriving.value
    }

    @Test
    fun `starts idle`() {
        DrivingModeDetector().isDriving.value shouldBe false
    }

    @Test
    fun `quiet phone never transitions to driving`() {
        run(
            0f to 1_000,
            0.5f to 1_000,
            0f to 1_000,
        ) shouldBe false
    }

    @Test
    fun `one fast sample alone is not enough to arm driving`() {
        run(
            25f to 1_000, // 90 km/h but only for an instant
            0f to 1_000,
        ) shouldBe false
    }

    @Test
    fun `sustained above-enter for enter duration arms driving`() {
        run(
            10f to 1_000,
            10f to 14_000, // +14 s, still ramping
            10f to 1_000,  // now 15 s cumulative → Driving
        ) shouldBe true
    }

    @Test
    fun `interrupted speedup returns to idle`() {
        run(
            10f to 1_000,
            10f to 10_000,  // 10 s of fast — still SpeedingUp
            0f to 1_000,    // dropped before 15 s → abandoned
            10f to 1_000,   // restart, but not enough duration yet
        ) shouldBe false
    }

    @Test
    fun `brief stop inside driving stays in driving via grace window`() {
        val detector = DrivingModeDetector()
        // Climb into driving.
        detector.onSample(10f, 1_000)
        detector.onSample(10f, 16_000) // Driving
        detector.isDriving.value shouldBe true
        // A red-light stop — driving should remain true.
        detector.onSample(0f, 17_000)  // SlowingDown starts
        detector.isDriving.value shouldBe true
        detector.onSample(0f, 60_000)  // 43 s of stopped — still SlowingDown
        detector.isDriving.value shouldBe true
    }

    @Test
    fun `long stop ends driving after exit duration`() {
        val detector = DrivingModeDetector()
        detector.onSample(10f, 1_000)
        detector.onSample(10f, 16_000)  // Driving
        detector.onSample(0f, 17_000)   // SlowingDown start
        detector.onSample(0f, 138_000)  // 121 s later — past EXIT_DURATION_MS
        detector.isDriving.value shouldBe false
    }

    @Test
    fun `accelerating out of a stop returns to driving`() {
        val detector = DrivingModeDetector()
        detector.onSample(10f, 1_000)
        detector.onSample(10f, 16_000)  // Driving
        detector.onSample(0f, 17_000)   // SlowingDown
        detector.onSample(10f, 30_000)  // back to Driving before EXIT_DURATION
        detector.isDriving.value shouldBe true
    }

    @Test
    fun `speed in hysteresis band preserves state`() {
        val detector = DrivingModeDetector()
        detector.onSample(10f, 1_000)
        detector.onSample(10f, 16_000)  // Driving
        // 3 m/s (~11 km/h) is between exit (1.4) and enter (5.5) — stays.
        detector.onSample(3f, 17_000)
        detector.isDriving.value shouldBe true
        detector.onSample(3f, 120_000)
        detector.isDriving.value shouldBe true
    }

    @Test
    fun `reset clears state`() {
        val detector = DrivingModeDetector()
        detector.onSample(10f, 1_000)
        detector.onSample(10f, 16_000)
        detector.isDriving.value shouldBe true
        detector.reset()
        detector.isDriving.value shouldBe false
    }
}
