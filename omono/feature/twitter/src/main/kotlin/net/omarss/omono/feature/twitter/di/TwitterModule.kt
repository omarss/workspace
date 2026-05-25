package net.omarss.omono.feature.twitter.di

import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import net.omarss.omono.feature.twitter.TweetsClient
import net.omarss.omono.feature.twitter.TweetsSource

// Mirrors PlacesModule — bind the interface to the OkHttp client so the
// repository receives the concrete implementation by default while
// tests can substitute a fake TweetsSource without touching DI graph
// internals.
@Module
@InstallIn(SingletonComponent::class)
abstract class TwitterModule {

    @Binds
    abstract fun bindTweetsSource(impl: TweetsClient): TweetsSource
}
