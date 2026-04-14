package net.omarss.omono.feature.speed

import androidx.datastore.preferences.core.edit
import androidx.test.core.app.ApplicationProvider
import app.cash.turbine.test
import io.kotest.matchers.shouldBe
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.data.omonoDataStore
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

// Robolectric round-trip test for SpeedSettingsRepository against a real
// (temporary) DataStore — confirms the prefix-namespaced key schema is
// readable and that setUnit propagates through the Flow without races.
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SpeedSettingsRepositoryTest {

    // omonoDataStore is bound to the Application context as a singleton,
    // so Robolectric reuses the same store across test methods. Wipe it
    // before each test to keep them independent.
    @Before
    fun resetDataStore() {
        runBlocking {
            val context = ApplicationProvider.getApplicationContext<android.content.Context>()
            context.omonoDataStore.edit { it.clear() }
        }
    }

    @Test
    fun `default unit is kilometers per hour`() = runTest {
        val repo = SpeedSettingsRepository(ApplicationProvider.getApplicationContext())
        repo.unit.test {
            awaitItem() shouldBe SpeedUnit.KmH
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `setUnit persists and emits the new value`() = runTest {
        val repo = SpeedSettingsRepository(ApplicationProvider.getApplicationContext())
        repo.unit.test {
            awaitItem() shouldBe SpeedUnit.KmH
            repo.setUnit(SpeedUnit.Mph)
            awaitItem() shouldBe SpeedUnit.Mph
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `each unit round-trips through the data store`() = runTest {
        val repo = SpeedSettingsRepository(ApplicationProvider.getApplicationContext())
        for (unit in SpeedUnit.entries) {
            repo.setUnit(unit)
            repo.unit.test {
                awaitItem() shouldBe unit
                cancelAndIgnoreRemainingEvents()
            }
        }
    }
}
