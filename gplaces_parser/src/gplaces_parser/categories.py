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
    ("salon",       "حلاق",                    "barber shop"),
    ("laundry",     "مغسلة",                   "laundry"),
    ("post_office", "مكتب بريد",               "post office"),
]


CATEGORIES: list[tuple[str, str]] = [
    pair for slug, ar, en in _SLUG_QUERIES for pair in ((slug, ar), (slug, en))
]

ALLOWED_SLUGS: frozenset[str] = frozenset(slug for slug, _, _ in _SLUG_QUERIES)
