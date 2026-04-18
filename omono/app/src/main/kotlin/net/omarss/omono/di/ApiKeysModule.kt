package net.omarss.omono.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import net.omarss.omono.BuildConfig
import javax.inject.Named
import javax.inject.Singleton

// Exposes build-time API keys (loaded from local.properties via
// BuildConfig fields in app/build.gradle.kts) to the rest of the DI
// graph. Feature modules inject with @Named so they don't need to
// depend on :app for BuildConfig access.
@Module
@InstallIn(SingletonComponent::class)
object ApiKeysModule {

    @Provides
    @Singleton
    @Named("gplacesApiUrl")
    fun provideGPlacesApiUrl(): String = BuildConfig.GPLACES_API_URL

    @Provides
    @Singleton
    @Named("gplacesApiKey")
    fun provideGPlacesApiKey(): String = BuildConfig.GPLACES_API_KEY
}
