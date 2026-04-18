"""Arabic search categories — slugs kept in lockstep with FEEDBACK.md.

The 19 entries below are the exact slug enum the omono client sends
(`PlaceCategory.slug`). They're used both as the scraper's `category`
column on `places` and as the `category` query-parameter the API takes.
Keeping slugs identical on both sides means `/v1/nearby?category=coffee`
maps to `WHERE category='coffee'` with no translation layer.

Each pair is (slug, arabic_query). Arabic queries match the hints in
FEEDBACK.md §4.
"""

CATEGORIES: list[tuple[str, str]] = [
    ("coffee",      "مقاهي"),
    ("restaurant",  "مطاعم"),
    ("fast_food",   "وجبات سريعة"),
    ("bakery",      "مخبز"),
    ("grocery",     "سوبر ماركت"),
    ("mall",        "مول"),
    ("fuel",        "محطة وقود"),
    ("ev_charger",  "شاحن سيارة كهربائية"),
    ("car_wash",    "غسيل سيارات"),
    ("pharmacy",    "صيدلية"),
    ("hospital",    "مستشفى"),
    ("gym",         "نادي رياضي"),
    ("park",        "حديقة"),
    ("bank",        "بنك"),
    ("atm",         "صراف آلي"),
    ("mosque",      "مسجد"),
    ("salon",       "حلاق"),
    ("laundry",     "مغسلة"),
    ("post_office", "مكتب بريد"),
]

ALLOWED_SLUGS: frozenset[str] = frozenset(slug for slug, _ in CATEGORIES)
