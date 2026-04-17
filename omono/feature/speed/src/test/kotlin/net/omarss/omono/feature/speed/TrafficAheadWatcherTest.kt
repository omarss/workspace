package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import io.kotest.matchers.shouldNotBe
import kotlinx.coroutines.test.runTest
import org.junit.Test

class TrafficAheadWatcherTest {

    // A hand-wired fake so the watcher can be exercised without an
    // HTTP round-trip. Records every call for assertion; returns
    // whatever the test stages next.
    private class FakeSource : TrafficFlowSource {
        var next: TrafficSample? = null
        var calls = 0
        val lastPoint = mutableListOf<Pair<Double, Double>>()

        override suspend fun sample(lat: Double, lon: Double): TrafficSample? {
            calls += 1
            lastPoint += lat to lon
            return next
        }
    }

    private val drivingSnapshot = LocationSnapshot(
        latitude = 24.7000,
        longitude = 46.7000,
        speedMps = 20f,                // ~72 km/h
        accuracyMeters = 4f,
        bearingDeg = 90f,              // heading east
        bearingAccuracyDeg = 5f,
    )

    // --- gating ------------------------------------------------------

    @Test
    fun `skips when speed below driving threshold`() = runTest {
        val fake = FakeSource().apply { next = jam() }
        val watcher = TrafficAheadWatcher(fake)
        val slow = drivingSnapshot.copy(speedMps = 2f)
        watcher.onLocation(slow, nowMs = 1_000) shouldBe null
        fake.calls shouldBe 0
    }

    @Test
    fun `skips when bearing is missing`() = runTest {
        val fake = FakeSource().apply { next = jam() }
        val watcher = TrafficAheadWatcher(fake)
        val noBearing = drivingSnapshot.copy(bearingDeg = null)
        watcher.onLocation(noBearing, nowMs = 1_000) shouldBe null
        fake.calls shouldBe 0
    }

    @Test
    fun `skips when bearing uncertainty is too high`() = runTest {
        val fake = FakeSource().apply { next = jam() }
        val watcher = TrafficAheadWatcher(fake)
        val noisy = drivingSnapshot.copy(bearingAccuracyDeg = 45f)
        watcher.onLocation(noisy, nowMs = 1_000) shouldBe null
        fake.calls shouldBe 0
    }

    @Test
    fun `polls when bearing accuracy is unknown on older devices`() = runTest {
        val fake = FakeSource().apply { next = freeFlow() }
        val watcher = TrafficAheadWatcher(fake)
        val unknownAccuracy = drivingSnapshot.copy(bearingAccuracyDeg = null)
        watcher.onLocation(unknownAccuracy, nowMs = 1_000) shouldBe null
        fake.calls shouldBe 0  // MAX_VALUE uncertainty gate blocks it
    }

    // --- triggering --------------------------------------------------

    @Test
    fun `emits warning when ratio is below threshold with high confidence`() = runTest {
        val fake = FakeSource().apply { next = jam() }
        val watcher = TrafficAheadWatcher(fake)
        val warning = watcher.onLocation(drivingSnapshot, nowMs = 1_000)
        warning shouldNotBe null
        warning!!.currentKmh shouldBe 20f
        warning.freeFlowKmh shouldBe 80f
        fake.calls shouldBe 1
    }

    @Test
    fun `no warning when traffic is at free-flow speed`() = runTest {
        val fake = FakeSource().apply { next = freeFlow() }
        val watcher = TrafficAheadWatcher(fake)
        watcher.onLocation(drivingSnapshot, nowMs = 1_000) shouldBe null
    }

    @Test
    fun `road closure always triggers regardless of confidence`() = runTest {
        val fake = FakeSource().apply {
            next = TrafficSample(
                currentSpeedKmh = 70f,
                freeFlowSpeedKmh = 80f,
                confidence = 0.1f,       // not confident…
                roadClosure = true,       // …but road is closed
            )
        }
        val watcher = TrafficAheadWatcher(fake)
        watcher.onLocation(drivingSnapshot, nowMs = 1_000) shouldNotBe null
    }

    @Test
    fun `low confidence suppresses slowdown warning`() = runTest {
        val fake = FakeSource().apply { next = jam().copy(confidence = 0.3f) }
        val watcher = TrafficAheadWatcher(fake)
        watcher.onLocation(drivingSnapshot, nowMs = 1_000) shouldBe null
    }

    // --- throttle + dedupe -------------------------------------------

    @Test
    fun `polls at most once per 30 seconds`() = runTest {
        val fake = FakeSource().apply { next = jam() }
        val watcher = TrafficAheadWatcher(fake)

        watcher.onLocation(drivingSnapshot, nowMs = 1_000) shouldNotBe null
        watcher.onLocation(drivingSnapshot, nowMs = 5_000) shouldBe null      // 4 s later, throttled
        watcher.onLocation(drivingSnapshot, nowMs = 20_000) shouldBe null     // 19 s later, still throttled
        fake.calls shouldBe 1
    }

    @Test
    fun `dedupes warnings in the same cell within five minutes`() = runTest {
        val fake = FakeSource().apply { next = jam() }
        val watcher = TrafficAheadWatcher(fake)

        watcher.onLocation(drivingSnapshot, nowMs = 0) shouldNotBe null
        // 31 s later, past the poll throttle but still in the same cell.
        watcher.onLocation(drivingSnapshot, nowMs = 31_000) shouldBe null
        fake.calls shouldBe 2
    }

    @Test
    fun `re-fires in a new cell even inside the dedupe window`() = runTest {
        val fake = FakeSource().apply { next = jam() }
        val watcher = TrafficAheadWatcher(fake)

        watcher.onLocation(drivingSnapshot, nowMs = 0) shouldNotBe null
        // Move far enough east that the look-ahead point lands in a new cell.
        val moved = drivingSnapshot.copy(longitude = drivingSnapshot.longitude + 0.01)
        watcher.onLocation(moved, nowMs = 31_000) shouldNotBe null
    }

    // --- fixtures ----------------------------------------------------

    private fun jam() = TrafficSample(
        currentSpeedKmh = 20f,
        freeFlowSpeedKmh = 80f,
        confidence = 0.9f,
        roadClosure = false,
    )

    private fun freeFlow() = TrafficSample(
        currentSpeedKmh = 78f,
        freeFlowSpeedKmh = 80f,
        confidence = 0.9f,
        roadClosure = false,
    )
}
