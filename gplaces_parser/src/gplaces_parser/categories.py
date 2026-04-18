"""Bilingual search categories — slugs match FEEDBACK.md §4.

Each slug is crawled with *both* an Arabic and an English query so the
feed surfaces places that Google ranks differently per language — an
Arabic-only tea house shows up on "مقاهي" but not "coffee shops", and
an international chain like Starbucks ranks better on the English side.

`CATEGORIES` is flattened (one row per slug × query pair) so the seed
pass can do a straightforward Cartesian product with the tile grid.
"""

# (slug, arabic_query, english_query) — the slug is what we persist on
# `places.category` and what the omono client sends.
_SLUG_QUERIES: list[tuple[str, str, str]] = [
    ("coffee",      "مقاهي",                  "coffee shops"),
    ("restaurant",  "مطاعم",                   "restaurants"),
    ("fast_food",   "وجبات سريعة",             "fast food"),
    ("bakery",      "مخبز",                    "bakery"),
    ("grocery",     "سوبر ماركت",              "supermarket"),
    ("mall",        "مول",                     "shopping mall"),
    ("fuel",        "محطة وقود",               "gas station"),
    ("ev_charger",  "شاحن سيارة كهربائية",     "ev charging station"),
    ("car_wash",    "غسيل سيارات",             "car wash"),
    ("pharmacy",    "صيدلية",                  "pharmacy"),
    ("hospital",    "مستشفى",                  "hospital"),
    ("gym",         "نادي رياضي",              "gym"),
    ("park",        "حديقة",                   "park"),
    ("bank",        "بنك",                     "bank"),
    ("atm",         "صراف آلي",                "atm"),
    ("mosque",      "مسجد",                    "mosque"),
    # `جامع` (Friday mosque) is normally bigger than a `مسجد` and many
    # big Riyadh mosques are only tagged this way in OSM / Google.
    ("mosque",      "جامع",                    "grand mosque"),
    ("salon",       "حلاق",                    "barber shop"),
    ("laundry",     "مغسلة",                   "laundry"),
    ("post_office", "مكتب بريد",               "post office"),
    # `library` covers two things the omono agent conflated: pure public
    # reading libraries AND coffee shops that stock books. Two query
    # families target each; the slug is one so the client side doesn't
    # have to pick. Dedup by place_id downstream handles Jarir-style
    # bookstores that show up under multiple queries.
    ("library",     "مكتبة عامة",              "public library"),
    ("library",     "كافيه مكتبة",             "book cafe"),
    # Transit — bus / metro / train / taxi / railway stations. Lumped
    # under one slug because the client mostly wants "stations nearby"
    # and Riyadh's transit is fragmented (SAPTCO + Metro + SAR).
    ("transit",     "محطة حافلات",             "bus station"),
    ("transit",     "محطة مترو",               "metro station"),
    ("transit",     "محطة قطار",               "train station"),
    ("transit",     "محطة سكة حديد",           "railway station"),
    ("transit",     "موقف سيارات أجرة",         "taxi stand"),
]


CATEGORIES: list[tuple[str, str]] = [
    pair for slug, ar, en in _SLUG_QUERIES for pair in ((slug, ar), (slug, en))
]

ALLOWED_SLUGS: frozenset[str] = frozenset(slug for slug, _, _ in _SLUG_QUERIES)
