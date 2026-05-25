package net.omarss.omono.feature.twitter

// Locations the Feed tab's multi-select filter offers. Two top-level
// country toggles plus a curated city list scoped to KSA + Egypt.
//
// Cities are matched server-side as case-insensitive substrings against
// the tweet's `place` field. X's `place_country:` operator gives us the
// country narrowing for free; per-city narrowing happens after the
// scrape since X has no `place_city:` operator.
//
// The list is intentionally curated rather than auto-derived from the
// scraped feed: the UI is a fixed dropdown, and the cities here are
// the ones with enough Twitter geo-tag density to give meaningful
// results in practice. New cities can be added by hand when warranted.

sealed interface LocationOption {
    val id: String
    val label: String
    val country: Country
}

data class CountryOption(
    val countryEnum: Country,
) : LocationOption {
    override val id: String = "country:${countryEnum.code}"
    override val label: String = countryEnum.label
    override val country: Country get() = countryEnum
}

data class CityOption(
    override val country: Country,
    val city: String,
    val arabic: String? = null,
) : LocationOption {
    override val id: String = "city:${country.code}:$city"
    // Label combines English + Arabic when both are known so the
    // dropdown reads naturally in either language.
    override val label: String = if (arabic != null) "$city · $arabic" else city
}

object LocationCatalog {

    val countries: List<CountryOption> = listOf(
        CountryOption(Country.KSA),
        CountryOption(Country.Egypt),
    )

    // KSA cities — every place that has appeared in live geo-tagged
    // scrapes plus the obvious large urban centres. Order: religious
    // significance first (most Twitter activity tags Hajj-related
    // posts there), then capital, then the rest by approximate
    // metropolitan population.
    val ksaCities: List<CityOption> = listOf(
        CityOption(Country.KSA, "Makkah Al Mukarrama", "مكة المكرمة"),
        CityOption(Country.KSA, "Al Madinah Al Munawwarah", "المدينة المنورة"),
        CityOption(Country.KSA, "Riyadh", "الرياض"),
        CityOption(Country.KSA, "Jeddah", "جدة"),
        CityOption(Country.KSA, "Dammam", "الدمام"),
        CityOption(Country.KSA, "Khobar", "الخبر"),
        CityOption(Country.KSA, "Taif", "الطائف"),
        CityOption(Country.KSA, "Tabuk", "تبوك"),
        CityOption(Country.KSA, "Abha", "أبها"),
        CityOption(Country.KSA, "Hail", "حائل"),
        CityOption(Country.KSA, "Qassim", "القصيم"),
        CityOption(Country.KSA, "Jazan", "جازان"),
        CityOption(Country.KSA, "Dhahran", "الظهران"),
        CityOption(Country.KSA, "Buraydah", "بريدة"),
        CityOption(Country.KSA, "Unayzah", "عنيزة"),
        CityOption(Country.KSA, "Al Majmah", "المجمعة"),
        CityOption(Country.KSA, "Thadiq", "ثادق"),
        CityOption(Country.KSA, "NEOM", "نيوم"),
    )

    val egyptCities: List<CityOption> = listOf(
        CityOption(Country.Egypt, "Cairo", "القاهرة"),
        CityOption(Country.Egypt, "Giza", "الجيزة"),
        CityOption(Country.Egypt, "Alexandria", "الإسكندرية"),
        CityOption(Country.Egypt, "Aswan", "أسوان"),
        CityOption(Country.Egypt, "Luxor", "الأقصر"),
        CityOption(Country.Egypt, "Hurghada", "الغردقة"),
        CityOption(Country.Egypt, "Sharm El Sheikh", "شرم الشيخ"),
        CityOption(Country.Egypt, "Mansoura", "المنصورة"),
        CityOption(Country.Egypt, "Tanta", "طنطا"),
        CityOption(Country.Egypt, "Suez", "السويس"),
    )

    /** All options grouped by country, ready for a Compose list. */
    val grouped: Map<Country, List<LocationOption>> = mapOf(
        Country.KSA to (listOf(CountryOption(Country.KSA)) + ksaCities),
        Country.Egypt to (listOf(CountryOption(Country.Egypt)) + egyptCities),
    )

    val all: List<LocationOption> = grouped.values.flatten()

    val defaults: Set<LocationOption> = setOf(CountryOption(Country.KSA))
}

// LocationFilter represents the user's current selection. Splits into
// the countries + cities pair the network layer needs.
data class LocationFilter(val selected: Set<LocationOption>) {

    /** Countries to send as ?country=ksa,eg. Empty defaults to all of
     *  KSA when nothing is selected (so the feed isn't blank). */
    val countries: List<Country>
        get() {
            // A CountryOption selects its country wholesale; a CityOption
            // implicitly includes its parent country (so EG-only cities
            // still get the `?country=eg` filter on the wire).
            val countrySet = mutableSetOf<Country>()
            for (opt in selected) {
                countrySet.add(opt.country)
            }
            return countrySet.ifEmpty { setOf(Country.KSA) }.toList()
        }

    /** Cities to send as ?city=...,...,... — empty when only country
     *  options are selected (= full-country feed). */
    val cities: List<String>
        get() {
            // If any country option is selected, that country acts as a
            // superset — drop city filters within that country since
            // they'd narrow further than the user asked.
            val supersetCountries = selected.filterIsInstance<CountryOption>()
                .map { it.country }
                .toSet()
            return selected
                .filterIsInstance<CityOption>()
                .filterNot { it.country in supersetCountries }
                .map { it.city }
        }

    val isEmpty: Boolean get() = selected.isEmpty()
}
