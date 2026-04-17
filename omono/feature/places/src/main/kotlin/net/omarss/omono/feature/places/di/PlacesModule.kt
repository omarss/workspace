package net.omarss.omono.feature.places.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import net.omarss.omono.feature.places.GPlacesClient
import net.omarss.omono.feature.places.PlacesSource
import net.omarss.omono.feature.places.TomTomSearchClient
import timber.log.Timber
import javax.inject.Singleton

// Picks the POI backend. When the self-hosted Google Places proxy is
// configured (base URL + API key present in local.properties) it wins;
// otherwise we fall back to the TomTom public API so a fresh clone
// with a TomTom key still has a working places feature. Both
// implementations live in the same module so the switch is a single
// line change — no mock/fake plumbing.
@Module
@InstallIn(SingletonComponent::class)
object PlacesModule {

    @Provides
    @Singleton
    fun providePlacesSource(
        gplaces: GPlacesClient,
        tomtom: TomTomSearchClient,
    ): PlacesSource = if (gplaces.isConfigured) {
        Timber.i("Places backend: self-hosted GPlaces")
        gplaces
    } else {
        Timber.i("Places backend: TomTom (fallback)")
        tomtom
    }
}
