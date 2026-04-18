package net.omarss.omono.feature.speed

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

// Thin state holder for the street / road name shown on the Tracking
// hero. Populated by SpeedFeature, which already runs the road lookup
// for the speed-limit number and reuses the same cached response
// (see FEEDBACK.md §6 — one `/v1/roads` call yields both fields).
//
// Previously this class owned an Android `Geocoder` + its own rate
// limiter. That logic is gone: the server-side endpoint returns names
// (in Arabic and English) alongside the speed limit, so a dedicated
// reverse-geocoding path is redundant. Keeping the class around as a
// broadcaster so OmonoMainViewModel's StateFlow wiring doesn't change
// shape.
@Singleton
class StreetNameResolver @Inject constructor() {

    private val _street = MutableStateFlow<String?>(null)
    val street: StateFlow<String?> = _street.asStateFlow()

    // Push the best available display name from the current
    // `/v1/roads` response. Caller picks between `name` (Arabic) and
    // `name_en` (English); we store whatever they hand us verbatim
    // and only filter blanks.
    fun setName(name: String?) {
        _street.value = name?.takeIf { it.isNotBlank() }
    }

    fun reset() {
        _street.value = null
    }
}
