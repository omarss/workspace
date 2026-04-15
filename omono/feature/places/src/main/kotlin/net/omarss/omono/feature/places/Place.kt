package net.omarss.omono.feature.places

// A single point of interest returned by the search API. Distance and
// bearing from the user's current position are filled in by the
// repository before the UI sees it — keeping the pure coordinates on
// the model means the UI layer never needs a reference point.
data class Place(
    val id: String,
    val name: String,
    val category: PlaceCategory,
    val latitude: Double,
    val longitude: Double,
    val distanceMeters: Double,
    val bearingDegrees: Float,
    val address: String?,
    val phone: String?,
)

// User-facing categories with the TomTom Search API category set IDs
// each one maps to. TomTom uses numeric IDs rather than names; the
// mapping is documented at
// https://developer.tomtom.com/search-api/documentation/product-information/supported-categories
enum class PlaceCategory(val label: String, val icon: String, val tomTomIds: List<Int>) {
    COFFEE("Coffee", "☕", listOf(9376006)),
    RESTAURANT("Restaurants", "🍽", listOf(7315)),
    FAST_FOOD("Fast food", "🍔", listOf(7315002)),
    GROCERY("Groceries", "🛒", listOf(7332, 9361051)),
    FUEL("Fuel", "⛽", listOf(7311)),
    PHARMACY("Pharmacy", "💊", listOf(9565003)),
    ATM("ATM", "🏧", listOf(7397)),
    MOSQUE("Mosque", "🕌", listOf(7339003)),
    HOSPITAL("Hospital", "🏥", listOf(7321)),
}
