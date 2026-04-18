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
    SUBSCRIPTIONS("Subscriptions"),
    HEALTHCARE("Healthcare"),
    OTHER("Other"),
}

// Maps a merchant string (from an SMS "At:" or "From:" field) to a
// SpendingCategory. Lookups consult user-authored overrides first
// — tap-to-correct on a transaction row — and fall back to the
// ordered keyword table below, first-hit-wins.
object MerchantCategorizer {

    fun categorize(
        merchant: String?,
        overrides: Map<String, SpendingCategory> = emptyMap(),
    ): SpendingCategory {
        if (merchant.isNullOrBlank()) return SpendingCategory.OTHER
        overrides[normaliseMerchantKey(merchant)]?.let { return it }
        val needle = merchant.lowercase()
        for ((keyword, category) in KEYWORDS) {
            if (needle.contains(keyword)) return category
        }
        return SpendingCategory.OTHER
    }

    // Ordered — more specific keywords first so a "ninja retail" hits
    // GROCERIES before a generic "retail" hits SHOPPING. Scraped from
    // the user's own SMS dump and expanded with the most common
    // Saudi merchants + subscription SaaS.
    private val KEYWORDS: List<Pair<String, SpendingCategory>> = listOf(
        // --- Food & delivery ---
        "jahez" to SpendingCategory.FOOD,
        "hungerstation" to SpendingCategory.FOOD,
        "toyou" to SpendingCategory.FOOD,
        "mrsool" to SpendingCategory.FOOD,
        "the chefz" to SpendingCategory.FOOD,
        "talabat" to SpendingCategory.FOOD,
        "ninja food" to SpendingCategory.FOOD,
        "java time" to SpendingCategory.FOOD,
        "starbucks" to SpendingCategory.FOOD,
        "dunkin" to SpendingCategory.FOOD,
        "costa" to SpendingCategory.FOOD,
        "tim hortons" to SpendingCategory.FOOD,
        "half million" to SpendingCategory.FOOD,
        "row cafe" to SpendingCategory.FOOD,
        "ucoffe" to SpendingCategory.FOOD,
        "cafe" to SpendingCategory.FOOD,
        "caffe" to SpendingCategory.FOOD,
        "cafè" to SpendingCategory.FOOD,
        "coffee" to SpendingCategory.FOOD,
        "restaurant" to SpendingCategory.FOOD,
        "mcdonald" to SpendingCategory.FOOD,
        "burger" to SpendingCategory.FOOD,
        "kfc" to SpendingCategory.FOOD,
        "pizza" to SpendingCategory.FOOD,
        "herfy" to SpendingCategory.FOOD,
        "albaik" to SpendingCategory.FOOD,
        "shawarma" to SpendingCategory.FOOD,
        "shake shack" to SpendingCategory.FOOD,
        "bakery" to SpendingCategory.FOOD,
        "berain" to SpendingCategory.GROCERIES, // bottled water

        // --- Groceries / retail ---
        "ninja retail" to SpendingCategory.GROCERIES,
        "lulu" to SpendingCategory.GROCERIES,
        "panda" to SpendingCategory.GROCERIES,
        "danube" to SpendingCategory.GROCERIES,
        "tamimi" to SpendingCategory.GROCERIES,
        "carrefour" to SpendingCategory.GROCERIES,
        "bindawood" to SpendingCategory.GROCERIES,
        "al othaim" to SpendingCategory.GROCERIES,
        "othaim" to SpendingCategory.GROCERIES,
        "farm superstore" to SpendingCategory.GROCERIES,
        "manuel market" to SpendingCategory.GROCERIES,
        "nahdi" to SpendingCategory.HEALTHCARE, // pharmacy — overrides GROCERIES on "nahdi market"

        // --- Fuel ---
        "aldrees" to SpendingCategory.FUEL,
        "adnoc" to SpendingCategory.FUEL,
        "petromin" to SpendingCategory.FUEL,
        "shell" to SpendingCategory.FUEL,
        "sasco" to SpendingCategory.FUEL,
        "petrol" to SpendingCategory.FUEL,

        // --- Healthcare ---
        "dr. sulaiman al habib" to SpendingCategory.HEALTHCARE,
        "al habib" to SpendingCategory.HEALTHCARE,
        "saudi german" to SpendingCategory.HEALTHCARE,
        "dallah" to SpendingCategory.HEALTHCARE,
        "pharmacy" to SpendingCategory.HEALTHCARE,
        "sadiriya" to SpendingCategory.HEALTHCARE,
        "saidaliah" to SpendingCategory.HEALTHCARE,

        // --- Transport ---
        "careem" to SpendingCategory.TRANSPORT,
        "uber" to SpendingCategory.TRANSPORT,
        "yango" to SpendingCategory.TRANSPORT,
        "absher" to SpendingCategory.TRANSPORT,
        "saptco" to SpendingCategory.TRANSPORT,
        "metro" to SpendingCategory.TRANSPORT,
        "taxi" to SpendingCategory.TRANSPORT,
        "najm" to SpendingCategory.TRANSPORT, // insurance-claim ops; conservative bucket
        "traffic violations" to SpendingCategory.TRANSPORT, // Saher

        // --- Utilities / telecoms / bills ---
        "stc pay" to SpendingCategory.UTILITIES,
        "stc bank" to SpendingCategory.UTILITIES,
        "stc" to SpendingCategory.UTILITIES,
        "mobily" to SpendingCategory.UTILITIES,
        "zain" to SpendingCategory.UTILITIES,
        "saudi electric" to SpendingCategory.UTILITIES,
        "sec" to SpendingCategory.UTILITIES,
        "water" to SpendingCategory.UTILITIES,
        "nwc" to SpendingCategory.UTILITIES,
        "internet" to SpendingCategory.UTILITIES,
        "ejar" to SpendingCategory.UTILITIES,

        // --- Subscriptions (streaming + SaaS) ---
        "netflix" to SpendingCategory.SUBSCRIPTIONS,
        "spotify" to SpendingCategory.SUBSCRIPTIONS,
        "anghami" to SpendingCategory.SUBSCRIPTIONS,
        "youtube" to SpendingCategory.SUBSCRIPTIONS,
        "shahid" to SpendingCategory.SUBSCRIPTIONS,
        "disney" to SpendingCategory.SUBSCRIPTIONS,
        "apple.com" to SpendingCategory.SUBSCRIPTIONS,
        "apple services" to SpendingCategory.SUBSCRIPTIONS,
        "icloud" to SpendingCategory.SUBSCRIPTIONS,
        "google play" to SpendingCategory.SUBSCRIPTIONS,
        "google*" to SpendingCategory.SUBSCRIPTIONS,
        "claude" to SpendingCategory.SUBSCRIPTIONS,
        "anthropic" to SpendingCategory.SUBSCRIPTIONS,
        "openai" to SpendingCategory.SUBSCRIPTIONS,
        "chatgpt" to SpendingCategory.SUBSCRIPTIONS,
        "github" to SpendingCategory.SUBSCRIPTIONS,
        "cursor" to SpendingCategory.SUBSCRIPTIONS,
        "midjourney" to SpendingCategory.SUBSCRIPTIONS,
        "adobe" to SpendingCategory.SUBSCRIPTIONS,
        "dropbox" to SpendingCategory.SUBSCRIPTIONS,
        "notion" to SpendingCategory.SUBSCRIPTIONS,

        // --- Entertainment / leisure ---
        "cinema" to SpendingCategory.ENTERTAINMENT,
        "muvi" to SpendingCategory.ENTERTAINMENT,
        "vox" to SpendingCategory.ENTERTAINMENT,
        "amc" to SpendingCategory.ENTERTAINMENT,
        "bowling" to SpendingCategory.ENTERTAINMENT,
        "theme park" to SpendingCategory.ENTERTAINMENT,
        "boulevard" to SpendingCategory.ENTERTAINMENT,

        // --- Generic shopping (last-resort — specific merchants above) ---
        "amazon" to SpendingCategory.SHOPPING,
        "noon" to SpendingCategory.SHOPPING,
        "shein" to SpendingCategory.SHOPPING,
        "extra" to SpendingCategory.SHOPPING,
        "jarir" to SpendingCategory.SHOPPING,
        "ikea" to SpendingCategory.SHOPPING,
        "namshi" to SpendingCategory.SHOPPING,
        "zara" to SpendingCategory.SHOPPING,
        "h&m" to SpendingCategory.SHOPPING,
        "centrepoint" to SpendingCategory.SHOPPING,
        "redtag" to SpendingCategory.SHOPPING,
        "virgin megastore" to SpendingCategory.SHOPPING,

        // --- Auth deep-link in SMS body (ignore; won't hit purchase totals) ---
        "mobile app" to SpendingCategory.UTILITIES,
    )
}

// Display-time cleaner for merchant strings. Normalises the
// all-caps / trailing-code / payment-processor prefixes that the
// bank SMS often carry — "MF(Tur" → "MyFatoorah · Tur", "GOOGLE*NO"
// → "Google Play". Never used for category lookup; that's driven
// by normaliseMerchantKey (case-fold, no display changes) so
// override keys stay stable even if display formatting changes.
fun cleanMerchantName(raw: String?): String {
    if (raw.isNullOrBlank()) return "Unknown"
    val trimmed = raw.trim()
    // Map known ugly prefixes to their friendly form first.
    PREFIX_REMAPS.forEach { (prefix, replacement) ->
        if (trimmed.startsWith(prefix, ignoreCase = true)) {
            val tail = trimmed.substring(prefix.length).trim().trimStart('*', '(', ')').trim()
            return if (tail.isEmpty()) replacement else "$replacement · ${titleCase(tail)}"
        }
    }
    // Otherwise strip an asterisk-code suffix ("MERCHANT*ABC123") and
    // title-case what remains.
    val withoutCode = trimmed.replace(Regex("\\*\\S+$"), "").trim()
    return titleCase(withoutCode.ifEmpty { trimmed })
}

private fun titleCase(s: String): String {
    // If the string is entirely upper-case (typical SMS) or entirely
    // lower, re-case it word-by-word. If it already has mixed case
    // (e.g. "Java Time") leave it alone.
    if (s.any { it.isLowerCase() } && s.any { it.isUpperCase() }) return s
    return s.lowercase().split(" ").joinToString(" ") { word ->
        word.replaceFirstChar { ch -> if (ch.isLetter()) ch.uppercase() else ch.toString() }
    }
}

// Display prefixes. Order matters: longer / more specific first so
// "GOOGLE*NO" (Google Play for subscriptions) doesn't fall through
// to a generic "google".
private val PREFIX_REMAPS: List<Pair<String, String>> = listOf(
    "MF(" to "MyFatoorah",
    "GOOGLE*" to "Google Play",
    "APPLE.COM" to "Apple",
    "PAYPAL *" to "PayPal",
    "SP *" to "Shopify",
)
