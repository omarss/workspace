package net.omarss.omono.feature.spending.di

import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import dagger.multibindings.IntoSet
import net.omarss.omono.core.service.OmonoFeature
import net.omarss.omono.feature.spending.SpendingFeature

// The single line that registers SpendingFeature with the host
// service. Adding a new feature module follows exactly this pattern
// — no changes to :app or :core.
@Module
@InstallIn(SingletonComponent::class)
abstract class SpendingFeatureModule {

    @Binds
    @IntoSet
    abstract fun bindSpendingFeature(impl: SpendingFeature): OmonoFeature
}
