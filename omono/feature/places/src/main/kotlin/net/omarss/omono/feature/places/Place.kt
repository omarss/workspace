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
    // Operational state from Google — one of OPERATIONAL,
    // CLOSED_TEMPORARILY, CLOSED_PERMANENTLY, or null when Google
    // didn't surface it. UI layers that direct users toward a place
    // (compass quick-toggle pins, navigation shortcuts) should hide
    // any CLOSED_* entry so we don't route the driver to a dead
    // destination.
    val businessStatus: String? = null,
)

// User-facing categories. Each maps to a lowercase-snake slug that
// the gplaces backend accepts on the `category` query param — see
// GPlacesClient.slug and gplaces_parser/FEEDBACK.md.
//
// `isCuisine` flags the food-adjacent sub-slugs the backend accepts
// (FEEDBACK.md §9.11). They're narrower than the top-level buckets
// like RESTAURANT / FAST_FOOD / BAKERY and show up as a second chip
// row only when one of those food parents is selected, so the main
// chip row stays scannable.
enum class PlaceCategory(
    val label: String,
    val icon: String,
    val isCuisine: Boolean = false,
) {
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
    JUICE("Juice", "🥤"),

    // Cuisine sub-slugs — shown only when RESTAURANT / FAST_FOOD /
    // BAKERY is the active top-level pick. Each behaves as an
    // independent category on the backend (category=sushi etc.) so
    // picking one replaces the parent selection on the wire.
    SEAFOOD("Seafood", "🦐", isCuisine = true),
    SUSHI("Sushi", "🍣", isCuisine = true),
    BURGER("Burger", "🍔", isCuisine = true),
    PIZZA("Pizza", "🍕", isCuisine = true),
    SHAWARMA("Shawarma", "🥙", isCuisine = true),
    KABSA("Kabsa", "🍛", isCuisine = true),
    MANDI("Mandi", "🍖", isCuisine = true),
    STEAKHOUSE("Steakhouse", "🥩", isCuisine = true),
    ITALIAN_FOOD("Italian", "🍝", isCuisine = true),
    INDIAN_FOOD("Indian", "🍲", isCuisine = true),
    ASIAN_FOOD("Asian", "🍜", isCuisine = true),
    HEALTHY_FOOD("Healthy", "🥗", isCuisine = true),
    BREAKFAST("Breakfast", "🍳", isCuisine = true),
    DESSERT("Dessert", "🍰", isCuisine = true),
    ICE_CREAM("Ice cream", "🍨", isCuisine = true),
}
