package net.omarss.omono.feature.places

// A single point of interest returned by the search API. Distance and
// bearing from the user's current position are filled in by the
// repository before the UI sees it — keeping the pure coordinates on
// the model means the UI layer never needs a reference point.
//
// rating / reviewCount / openNow come from the gplaces backend when
// scraped Google data has them. TomTom fallback doesn't populate these
// so the UI treats them as optional.
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
    val rating: Float? = null,
    val reviewCount: Int? = null,
    val openNow: Boolean? = null,
)

// User-facing categories with the TomTom POI category IDs each one
// maps to. IDs verified against
//   https://api.tomtom.com/search/2/poiCategories.json?key=...&language=en-GB
// (the canonical source; the supported-categories docs page 404s as of
// April 2026).
//
// When adding a category, prefer the most specific ID that still
// covers the common cases in-country — e.g. 7320002 (Fitness Club &
// Center) rather than the much broader 7320 (Sports Center), which
// would also return stadiums.
enum class PlaceCategory(val label: String, val icon: String, val tomTomIds: List<Int>) {
    COFFEE("Coffee", "☕", listOf(9376006)),
    RESTAURANT("Restaurants", "🍽", listOf(7315)),
    FAST_FOOD("Fast food", "🍔", listOf(7315015)),
    BAKERY("Bakery", "🥐", listOf(9361018)),
    GROCERY("Groceries", "🛒", listOf(7332005, 9361023)),
    MALL("Mall", "🏬", listOf(7373)),
    FUEL("Fuel", "⛽", listOf(7311)),
    EV_CHARGER("EV charging", "🔌", listOf(7309)),
    CAR_WASH("Car wash", "🚗", listOf(9155, 9155002)),
    PHARMACY("Pharmacy", "💊", listOf(7326, 9361051)),
    HOSPITAL("Hospital", "🏥", listOf(7321)),
    GYM("Gym", "🏋", listOf(7320002)),
    PARK("Park", "🌳", listOf(9362008, 9362)),
    BANK("Bank", "🏦", listOf(7328)),
    ATM("ATM", "🏧", listOf(7397)),
    MOSQUE("Mosque", "🕌", listOf(7339003)),
    SALON("Salon", "💈", listOf(9361027)),
    LAUNDRY("Laundry", "🧺", listOf(9361045)),
    POST_OFFICE("Post", "📮", listOf(7324)),
}
