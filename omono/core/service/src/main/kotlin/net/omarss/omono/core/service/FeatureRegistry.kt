package net.omarss.omono.core.service

import javax.inject.Inject
import javax.inject.Singleton

// Hilt multibinding discovers every OmonoFeature the app ships. Features
// @Binds @IntoSet themselves from their own Hilt module; the registry just
// exposes them to the host service.
@Singleton
class FeatureRegistry @Inject constructor(
    private val features: Set<@JvmSuppressWildcards OmonoFeature>,
) {
    fun all(): Set<OmonoFeature> = features

    fun byId(id: FeatureId): OmonoFeature? = features.firstOrNull { it.id == id }
}
