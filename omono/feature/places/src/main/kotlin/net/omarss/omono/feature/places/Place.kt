package net.omarss.omono.feature.places

// A single point of interest returned by the search API. Distance and
// bearing from the user's current position are filled in by the
// repository before the UI sees it — keeping the pure coordinates on
// the model means the UI layer never needs a reference point.
//
// rating / reviewCount / openNow come from the gplaces backend when
// scraped Google data has them, and stay null otherwise.
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
    // Google Maps CID as a decimal string — when present, builds a
    // `maps.google.com/?cid=<n>` deep link that opens the place's
    // full detail panel (reviews, photos, hours). Server-provided
    // since v0.29.x; before that the client parsed it out of `id`.
    val cid: String? = null,
)

// User-facing categories. Each maps to a lowercase-snake slug that
// the gplaces backend accepts on the `category` query param — see
// GPlacesClient.slug and gplaces_parser/FEEDBACK.md.
enum class PlaceCategory(val label: String, val icon: String) {
    COFFEE("Coffee", "☕"),
    RESTAURANT("Restaurants", "🍽"),
    FAST_FOOD("Fast food", "🍔"),
    BAKERY("Bakery", "🥐"),
    GROCERY("Groceries", "🛒"),
    MALL("Mall", "🏬"),
    FUEL("Fuel", "⛽"),
    EV_CHARGER("EV charging", "🔌"),
    CAR_WASH("Car wash", "🚗"),
    PHARMACY("Pharmacy", "💊"),
    HOSPITAL("Hospital", "🏥"),
    GYM("Gym", "🏋"),
    PARK("Park", "🌳"),
    BANK("Bank", "🏦"),
    ATM("ATM", "🏧"),
    MOSQUE("Mosque", "🕌"),
    SALON("Salon", "💈"),
    LAUNDRY("Laundry", "🧺"),
    POST_OFFICE("Post", "📮"),
    LIBRARY("Library", "📚"),
    TRANSIT("Transit", "🚌"),
}
