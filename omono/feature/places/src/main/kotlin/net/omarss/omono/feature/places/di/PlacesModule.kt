package net.omarss.omono.feature.places.di

import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import net.omarss.omono.feature.places.GPlacesClient
import net.omarss.omono.feature.places.PlacesSource

// GPlaces is the only POI backend — the self-hosted gplaces_parser
// proxy served from api.omarss.net. PlacesSource is kept as a narrow
// interface so PlacesRepository stays testable without the HTTP
// stack, not because there's a second implementation.
@Module
@InstallIn(SingletonComponent::class)
abstract class PlacesModule {

    @Binds
    abstract fun bindPlacesSource(impl: GPlacesClient): PlacesSource
}
