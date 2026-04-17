package net.omarss.omono.feature.speed.di

import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import dagger.multibindings.IntoSet
import net.omarss.omono.core.service.OmonoFeature
import net.omarss.omono.feature.speed.SpeedFeature
import net.omarss.omono.feature.speed.TomTomTrafficFlowClient
import net.omarss.omono.feature.speed.TrafficFlowSource

// The one line that registers SpeedFeature with the host service.
// Every new feature module adds its own equivalent binding — nothing
// in :app or :core has to change.
@Module
@InstallIn(SingletonComponent::class)
abstract class SpeedFeatureModule {

    @Binds
    @IntoSet
    abstract fun bindSpeedFeature(impl: SpeedFeature): OmonoFeature

    // Narrow source interface lets TrafficAheadWatcher be unit-tested
    // against a fake without touching TomTom or OkHttp.
    @Binds
    abstract fun bindTrafficFlowSource(impl: TomTomTrafficFlowClient): TrafficFlowSource
}
