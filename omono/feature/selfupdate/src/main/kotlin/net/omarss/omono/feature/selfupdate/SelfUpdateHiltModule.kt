package net.omarss.omono.feature.selfupdate

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

// Hilt wiring for the self-updater. Kept inside the feature module so
// the app shell doesn't need to know about any of these types.
@Module
@InstallIn(SingletonComponent::class)
object SelfUpdateHiltModule {

    @Provides
    @Singleton
    fun provideSelfUpdateClient(): SelfUpdateClient = SelfUpdateClient()
}
