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
    # `clinic` — siphons the small-practice / medical-center rows off
    # the `hospital` slug so `category=hospital` returns true hospitals.
    # Dedicated queries seed new data under the clinic slug directly.
    ("clinic",      "عيادات",                  "clinic"),
    ("clinic",      "مجمع طبي",                "medical center"),
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
    # Juice bars — distinct from cafes/fast-food in Riyadh. Sugarcane
    # (قصب) is a local staple and deserves its own query to surface
    # the one-trick juice stalls that wouldn't show up under "juice bar".
    ("juice",       "عصائر",                   "juice bar"),
    ("juice",       "عصير قصب",                "sugarcane juice"),
    ("juice",       "عصائر طازجة",             "fresh juice"),
    # Sub-category slugs — refinements of `restaurant` that Google
    # ranks differently enough to surface distinct places. Each is its
    # own slug so the API can filter cleanly (`category=seafood`).
    ("seafood",     "مطاعم أسماك",             "seafood restaurant"),
    ("healthy_food","أكل صحي",                 "healthy food"),
    ("italian_food","مطاعم إيطالية",           "italian restaurant"),
    ("sushi",       "سوشي",                    "sushi"),
    ("burger",      "برجر",                    "burger joint"),
    ("pizza",       "بيتزا",                   "pizzeria"),
    ("shawarma",    "شاورما",                  "shawarma"),
    ("kabsa",       "كبسة",                    "kabsa"),
    ("mandi",       "مندي",                    "mandi restaurant"),
    ("steakhouse",  "ستيك",                    "steakhouse"),
    ("dessert",     "حلويات",                  "dessert shop"),
    ("ice_cream",   "آيس كريم",                "ice cream"),
    ("breakfast",   "فطور",                    "breakfast"),
    ("indian_food", "مطاعم هندية",             "indian restaurant"),
    ("asian_food",  "مطاعم آسيوية",            "asian restaurant"),
    # Museums + cultural / heritage sites. Two slugs because users ask
    # different things: `museum` → indoor collections, `cultural_site` →
    # outdoor heritage / monuments / historic districts.
    ("museum",      "متحف",                    "museum"),
    ("museum",      "متحف وطني",               "national museum"),
    ("cultural_site","معلم ثقافي",             "cultural landmark"),
    ("cultural_site","موقع تراثي",             "heritage site"),
    # Brunch as its own slug — `breakfast` catches traditional فطور
    # spots, this one surfaces modern brunch / all-day-breakfast cafes.
    ("brunch",      "برانش",                   "brunch"),
    ("brunch",      "برانش كافيه",             "brunch cafe"),
]


CATEGORIES: list[tuple[str, str]] = [
    pair for slug, ar, en in _SLUG_QUERIES for pair in ((slug, ar), (slug, en))
]

ALLOWED_SLUGS: frozenset[str] = frozenset(slug for slug, _, _ in _SLUG_QUERIES)
