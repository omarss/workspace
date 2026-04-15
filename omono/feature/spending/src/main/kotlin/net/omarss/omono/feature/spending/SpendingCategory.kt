package net.omarss.omono.feature.spending

// Coarse categorisation for the spending card. Keyword-based because
// a hand-curated map of Saudi merchants is good enough for the
// personal use case and avoids the complexity of a trained model or
// a crowdsourced dictionary.
enum class SpendingCategory(val label: String) {
    FOOD("Food & delivery"),
    GROCERIES("Groceries"),
    FUEL("Fuel"),
    TRANSPORT("Transport"),
    UTILITIES("Utilities"),
    SHOPPING("Shopping"),
    ENTERTAINMENT("Entertainment"),
    OTHER("Other"),
}

// Maps a merchant string (from an SMS "At:" or "From:" field) to a
// SpendingCategory. Matches are case-insensitive substring lookups
// against the ordered keyword table below — first hit wins, so the
// more specific keywords should come earlier.
object MerchantCategorizer {

    fun categorize(merchant: String?): SpendingCategory {
        if (merchant.isNullOrBlank()) return SpendingCategory.OTHER
        val needle = merchant.lowercase()
        for ((keyword, category) in KEYWORDS) {
            if (needle.contains(keyword)) return category
        }
        return SpendingCategory.OTHER
    }

    // Ordered — more specific keywords first so a "ninja retail" hits
    // GROCERIES before a generic "retail" hits SHOPPING.
    private val KEYWORDS: List<Pair<String, SpendingCategory>> = listOf(
        // Food & delivery
        "jahez" to SpendingCategory.FOOD,
        "hungerstation" to SpendingCategory.FOOD,
        "toyou" to SpendingCategory.FOOD,
        "mrsool" to SpendingCategory.FOOD,
        "the chefz" to SpendingCategory.FOOD,
        "talabat" to SpendingCategory.FOOD,
        "careem" to SpendingCategory.TRANSPORT,
        "uber" to SpendingCategory.TRANSPORT,
        "java time" to SpendingCategory.FOOD,
        "starbucks" to SpendingCategory.FOOD,
        "row cafe" to SpendingCategory.FOOD,
        "cafe" to SpendingCategory.FOOD,
        "coffee" to SpendingCategory.FOOD,
        "restaurant" to SpendingCategory.FOOD,
        "mcdonald" to SpendingCategory.FOOD,
        "burger" to SpendingCategory.FOOD,
        "kfc" to SpendingCategory.FOOD,

        // Groceries / retail
        "ninja retail" to SpendingCategory.GROCERIES,
        "ninja food" to SpendingCategory.FOOD,
        "lulu" to SpendingCategory.GROCERIES,
        "panda" to SpendingCategory.GROCERIES,
        "danube" to SpendingCategory.GROCERIES,
        "tamimi" to SpendingCategory.GROCERIES,
        "carrefour" to SpendingCategory.GROCERIES,
        "aldrees" to SpendingCategory.FUEL,

        // Fuel
        "adnoc" to SpendingCategory.FUEL,
        "petromin" to SpendingCategory.FUEL,
        "shell" to SpendingCategory.FUEL,
        "sasco" to SpendingCategory.FUEL,

        // Utilities / bills
        "stc pay" to SpendingCategory.UTILITIES,
        "stc" to SpendingCategory.UTILITIES,
        "mobily" to SpendingCategory.UTILITIES,
        "zain" to SpendingCategory.UTILITIES,
        "saudi electricity" to SpendingCategory.UTILITIES,
        "water" to SpendingCategory.UTILITIES,
        "nwc" to SpendingCategory.UTILITIES,
        "mobile app" to SpendingCategory.UTILITIES,

        // Transport
        "jahez" to SpendingCategory.FOOD,
        "absher" to SpendingCategory.TRANSPORT,
        "saptco" to SpendingCategory.TRANSPORT,
        "metro" to SpendingCategory.TRANSPORT,
        "taxi" to SpendingCategory.TRANSPORT,

        // Entertainment
        "netflix" to SpendingCategory.ENTERTAINMENT,
        "spotify" to SpendingCategory.ENTERTAINMENT,
        "cinema" to SpendingCategory.ENTERTAINMENT,
        "muvi" to SpendingCategory.ENTERTAINMENT,
        "vox" to SpendingCategory.ENTERTAINMENT,

        // Generic shopping
        "amazon" to SpendingCategory.SHOPPING,
        "noon" to SpendingCategory.SHOPPING,
        "extra" to SpendingCategory.SHOPPING,
        "jarir" to SpendingCategory.SHOPPING,
    )
}
