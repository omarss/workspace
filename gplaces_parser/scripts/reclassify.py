#!/usr/bin/env python3
"""Post-scrape reclassifier — corrects `places.category` based on the
real Google type in `subcategories[1]` + name-pattern fallbacks.

The scraper tags every hit with the query's slug regardless of what
Google actually calls the place. This re-routes misclassifications
and keeps each slug meaningful. Idempotent: safe to run repeatedly;
converges toward a clean state.

Run after every `make scrape-places` round:

    .venv/bin/python scripts/reclassify.py
"""
from __future__ import annotations

import psycopg

from gplaces_parser.config import settings


# Each rule: (from_slug, sql_filter, to_slug). from_slug='*' matches any
# current category; NULL targets are kept as-is downstream.
# Order matters — earlier rules fire first and the same row won't match
# twice in one run.

LIBRARY_PURGE = [
    # subcategory-driven: Google's own type is clearly not a library
    ("library", "subcategories[1] ~* 'cafe|café|coffee' OR subcategories[1] ~ 'مقهى|كافيه|قهوة'", "coffee"),
    ("library", "subcategories[1] ~* 'restaurant' OR subcategories[1] ~ 'مطعم'", "restaurant"),
    ("library",
     "subcategories[1] ~* 'electronics|bookstore|book store|stationery|office supplies|digital printing|print service|retail'"
     " OR subcategories[1] ~ 'متجر|قرطاسية|أدوات مكتبية|محل نسخ|خدمة طباعة|تاجر كتب|أثاث مكتبي|منفذ بيع'",
     "bookstore"),
    # Academic/government/research facilities that aren't libraries
    ("library",
     "subcategories[1] ~* 'university|college|department|academic|research|educational|institute|government'"
     " OR subcategories[1] ~ 'جامعة|كلية|قسم أكاديمي|معهد|مؤسسة تعليمية|مؤسسة دينية|مكتب حكومي|استشاري|إدارة|التربية والتعليم|رابطة|مستشار تعليمي|مكتب الشركات'",
     None),
    # Publishers / wholesale book dealers — not reading libraries
    ("library",
     "COALESCE(name, '') ~ 'للنشر|للتوزيع|دار .*نشر|دار الهدى|دار المقحم|دار الجداول|للطباعة|للنسخ|للتصوير|قرطاسية|للخدمات الطلابية|للخدمات العامة|خدمات الطالب'"
     " OR COALESCE(name_en, '') ~* 'publishing|distribution|wholesale'",
     "bookstore"),
    # Metro / subway stations with "library" in the name → transit
    ("library",
     "subcategories[1] ~* 'subway station|suburban train|transportation service|metro station|bus station'",
     "transit"),
    # Culture oasis / cultural park / science museum — these are cultural_site / museum
    ("library",
     "subcategories[1] ~* 'science museum|art museum|museum'",
     "museum"),
    ("library",
     "subcategories[1] ~* 'cultural center|community center'",
     "cultural_site"),
    # Nightlife (lounge bars) aren't libraries
    ("library",
     "subcategories[1] ~* 'lounge bar|bar|nightclub'",
     None),
    # Hospital departments / specialized admin — null
    ("library",
     "subcategories[1] ~* 'hospital department|local government office|consultant'",
     None),
    # Restaurant gtype (Bakery) snuck in via "King Fahd library" NAME
    # on a cafe; respect Google.
    ("library",
     "subcategories[1] ~* 'bakery|restaurant'",
     "restaurant"),
    ("library", "subcategories[1] ~* 'supermarket|hypermarket|grocery|market' OR subcategories[1] ~ 'سوبر|بقالة'", "grocery"),
    ("library", "subcategories[1] ~* 'park|garden' OR subcategories[1] ~ 'حديقة|منتزه'", "park"),
    ("library", "subcategories[1] ~* 'university|college|school' OR subcategories[1] ~ 'جامعة|كلية|مدرسة'", None),
    ("library", "subcategories[1] ~* 'shopping|mall'", "mall"),
    ("library", "subcategories[1] ~* 'hotel' OR subcategories[1] ~ 'فندق'", None),
    # name-driven: even when Google mis-calls these "Library" they're
    # copy/stationery/student-services shops.
    ("library",
     "COALESCE(name, '')    ~* 'copy center|copy centre|photocopy|stationery|bookstore|book shop|book store'"
     " OR COALESCE(name_en, '') ~* 'copy center|copy centre|photocopy|stationery|bookstore|book shop|book store'"
     " OR COALESCE(name, '')    ~ 'نسخ|تصوير|طباعة|للنشر|للتوزيع|خدمات الطالب|خدمات طالب|الخدمات الطلابية|للخدمات|للطلاب|قرطاسية|مركز ومكتبة|جرير|العبيكان|الرشد|دار الزهراء|أدوات مكتبية|التجليد|دعايه واعلان|دعاية|إعلان'"
     " OR COALESCE(name_en, '') ~* 'jarir|obeikan|office supplies|publishers|publishing|student|advertising'",
     "bookstore"),
    # Final: anything still in library whose subcategory explicitly is
    # NOT library → null out.
    ("library",
     "subcategories IS NOT NULL"
     " AND NOT (subcategories[1] ~* 'library|book' OR subcategories[1] ~ 'مكتبة|مكتبات')",
     None),
]

# Hospital vs clinic: if name signals clinic/polyclinic/center → clinic.
HOSPITAL_PURGE = [
    ("hospital",
     "NOT (COALESCE(name, '')    ~ 'مستشفى' OR COALESCE(name_en, '') ~* 'hospital')"
     " AND ("
     "   COALESCE(name, '')    ~ 'عيادة|عيادات|مجمع طبي|مركز طبي'"
     "   OR COALESCE(name_en, '') ~* 'clinic|medical center|medical complex|polyclinic'"
     "   OR COALESCE(reviews_count, 0) < 50"
     " )",
     "clinic"),
]

# Generic subcategory-driven routing. For each slug, define anti-patterns
# — if the subcategory[1] matches one of these, the row is clearly NOT
# that slug and gets moved (or nulled). Preserves places whose Google
# type genuinely matches the slug.
GENERIC_PURGE: list[tuple[str, str, str | None]] = [
    # laundry — filter out car-wash places mislabeled as laundry
    ("laundry",
     "subcategories[1] ~* 'car wash' OR subcategories[1] ~ 'غسيل سيارات|غسل سيارات|مغسلة سيارات'",
     "car_wash"),

    # healthy_food / ice_cream / sushi / kabsa etc — hypermarkets sneak in
    # Arabic + English coverage: سوق ضخمة / هايبر / سوبر ماركت all mean
    # hypermarket in Google's Arabic type labels.
    ("healthy_food", "subcategories[1] ~* 'hypermarket|supermarket' OR subcategories[1] ~ 'سوق ضخمة|هايبر|سوبر ماركت|بقالة'", "grocery"),
    ("ice_cream",    "subcategories[1] ~* 'hypermarket|supermarket' OR subcategories[1] ~ 'سوق ضخمة|هايبر|سوبر ماركت'", "grocery"),
    ("sushi",        "subcategories[1] ~* 'hypermarket|supermarket|hotel' OR subcategories[1] ~ 'سوق ضخمة|هايبر|فندق'", None),
    ("juice",        "subcategories[1] ~* 'hypermarket|supermarket|market' OR subcategories[1] ~ 'سوق ضخمة|هايبر|بقالة|حمام'", "grocery"),
    # juice name-level: remove bath houses (حمام = public bath, not juice)
    ("juice",        "COALESCE(name, '') ~ 'حمام'", None),

    # kabsa / shawarma / pizza / steakhouse — Google's type is cleaner
    # than the search query; respect it.
    ("kabsa",       "subcategories[1] ~* 'shawarma' OR subcategories[1] ~ 'شاورما'", "shawarma"),
    ("kabsa",       "subcategories[1] ~* 'burger'",  "burger"),
    ("pizza",       "subcategories[1] ~* 'egyptian|lebanese|indian|chinese' AND subcategories[1] !~* 'pizza'", "restaurant"),
    ("steakhouse",  "subcategories[1] ~* 'turkish|sandwich|chinese|indian' AND subcategories[1] !~* 'steak'", "restaurant"),
    ("italian_food","subcategories[1] !~* 'italian|pizza' AND subcategories[1] ~* 'restaurant'", "restaurant"),
    ("indian_food", "subcategories[1] !~* 'indian' AND subcategories[1] ~* 'restaurant'", "restaurant"),
    ("asian_food",  "subcategories[1] !~* 'chinese|thai|vietnamese|korean|japanese|asian|sushi' AND subcategories[1] ~* 'restaurant'", "restaurant"),
    ("seafood",     "subcategories[1] !~* 'seafood|fish' AND subcategories[1] ~* 'restaurant'", "restaurant"),

    # breakfast — shawarma / fast-food often leaks in under فطور queries
    ("breakfast",   "subcategories[1] ~* 'shawarma' OR subcategories[1] ~ 'شاورما'", "shawarma"),
    ("breakfast",   "subcategories[1] ~* 'fast food'", "fast_food"),

    # gym — hotels + sports club HQs (نادي الهلال = Al Hilal FC) aren't gyms
    ("gym",         "subcategories[1] ~* 'hotel|soccer club|football club' OR subcategories[1] ~ 'فندق|نادي كرة قدم'", None),
    ("gym",         "COALESCE(name, '') ~ 'نادي الهلال|نادي النصر|نادي الاتحاد|نادي الشباب'", None),

    # laundry — gas stations mis-scraped via مغسلة
    ("laundry",     "subcategories[1] ~* 'gas station' OR subcategories[1] ~ 'محطة وقود|بنزين'", "fuel"),

    # steakhouse — name-based fallback for places whose gtype is stale
    ("steakhouse",  "COALESCE(name, '') ~ 'ساندوتش|شاورما|برجر|بيتزا' OR COALESCE(name_en, '') ~* 'sandwich|shawarma|burger|pizza'", "restaurant"),

    # kabsa — Mama Noura serves kabsa + everything; let Google's "Middle
    # Eastern Restaurant" type route it back to restaurant if that's
    # what it really is.
    ("kabsa",       "subcategories[1] ~* 'middle eastern' AND subcategories[1] !~* 'kabsa'", "restaurant"),

    # clinic — massive hospitals pulled in by `مستشفى` variants; reviews
    # count plus hospital-name signal puts them back where they belong.
    ("clinic",
     "COALESCE(reviews_count, 0) >= 2000 AND (COALESCE(name, '') ~ 'مستشفى' OR COALESCE(name_en, '') ~* 'hospital')",
     "hospital"),
]

# Post-sampling fixes from the audits. Each rule addresses a concrete
# misclassification seen in the DB; keep them tight so they only match
# the noise and not legitimate rows.
CROSS_SLUG_PURGE: list[tuple[str, str, str | None]] = [
    # bank slug had "AlRajhi Bank ATM" etc — Google's gtype says ATM
    ("bank", "subcategories[1] ~* 'atm|cash machine'", "atm"),
    # bank slug also had "Saudi Investment Bank Parking" etc — drop
    ("bank",
     "subcategories[1] ~* 'parking|warehouse|office|storage'"
     " OR COALESCE(name, '') ~ 'مواقف' OR COALESCE(name_en, '') ~* 'parking'",
     None),

    # hospital has parking lots + mislabeled factories etc
    ("hospital",
     "COALESCE(name, '') ~ 'مواقف|مستودع' OR COALESCE(name_en, '') ~* 'parking|warehouse|storage'",
     None),
    ("hospital",
     "subcategories[1] ~* 'factory|office|store|warehouse|pharmacy' OR subcategories[1] ~ 'مصنع|مكتب|متجر|مستودع|صيدلية'",
     None),

    # park — business parks + parking plazas aren't public parks
    ("park",
     "subcategories[1] ~* 'corporate|parking|office|business park|plaza'"
     " OR COALESCE(name_en, '') ~* 'business park|parking plaza|office park'",
     None),

    # mall — shopping arcades only; drop single-shop inside malls + offices
    ("mall",
     "subcategories[1] ~* 'corporate|office|showroom|locksmith|parking' OR subcategories[1] ~ 'مكتب|معرض|مواقف'",
     None),

    # healthy_food — drop corporate / trading / animal-feed / yogurt
    ("healthy_food",
     "subcategories[1] ~* 'trading|corporate|company|office|animal feed|pet|wholesale'"
     " OR subcategories[1] ~ 'أعلاف|حبوب|متجر حيوانات|تجارة|شركة'"
     " OR COALESCE(name_en, '') ~* 'trading company|corporation|animal feed'"
     " OR COALESCE(name, '') ~ 'أعلاف|حبوب'",
     None),

    # sushi has corporate offices leaked in
    ("sushi",
     "subcategories[1] ~* 'corporate|office|company' OR subcategories[1] ~ 'مكتب الشركات|مكتب'",
     None),

    # steakhouse — farouj = chicken, salduwitch = sandwich
    ("steakhouse",
     "COALESCE(name, '') ~ 'فروج|ساندوتش|شاورما|برجر' OR COALESCE(name_en, '') ~* 'farouj|sandwich|shawarma|burger|chicken'",
     "restaurant"),

    # atm ≠ bank — keep things labeled Bank in the bank slug
    ("atm", "subcategories[1] ~* '^bank$' OR subcategories[1] ~ 'مصرف$'", "bank"),

    # dessert / ice_cream / juice with Coffee shop gtype → coffee
    ("dessert",
     "subcategories[1] ~* 'coffee shop|cafe|café' OR subcategories[1] ~ 'مقهى|كافيه'",
     "coffee"),
    ("juice",
     "subcategories[1] ~* 'coffee shop|cafe|café' OR subcategories[1] ~ 'مقهى|كافيه'",
     "coffee"),

    # ice_cream with Bakery gtype OR bakery name → bakery
    ("ice_cream",
     "subcategories[1] ~* 'bakery' OR subcategories[1] ~ 'مخبز'"
     " OR COALESCE(name, '') ~ 'مخبز' OR COALESCE(name_en, '') ~* 'bakery'",
     "bakery"),

    # mall with single-store gtype (shoe store, accessories, etc) → drop
    ("mall",
     "subcategories[1] ~* 'shoe store|clothing store|accessories|jewellery|jewelry|electronics store'"
     " OR subcategories[1] ~ 'متجر أحذية|متجر ملابس|متجر إكسسوارات|متجر مجوهرات|متجر إلكترونيات'",
     None),

    # steakhouse — shisha lounge is a restaurant, not a steakhouse
    ("steakhouse",
     "subcategories[1] ~* 'shisha|hookah lounge' OR subcategories[1] ~ 'مقهى للشيشة|الأرجيلة'",
     "restaurant"),
    # steakhouse tagged الإيطالي (Italian) → italian_food
    ("steakhouse",
     "subcategories[1] ~* 'italian' OR subcategories[1] ~ 'الإيطالي|إيطالي'",
     "italian_food"),

    # clinic with warehouse name (مستودع) → drop
    ("clinic",
     "COALESCE(name, '') ~ '^مستودع' OR COALESCE(name_en, '') ~* '^warehouse|storage facility'",
     None),

    # park with a coffee-brand name — dr.CAFE/Starbucks/Costa IN a park → coffee
    ("park",
     "subcategories[1] ~* 'coffee shop|cafe|café' OR subcategories[1] ~ 'مقهى|كافيه'"
     " OR COALESCE(name, '') ~ 'د\\.كيف|د\\. كيف|ستاربكس|كوستا'"
     " OR COALESCE(name_en, '') ~* 'dr\\.?\\s?cafe|starbucks|costa'",
     "coffee"),
]

ALL_RULES: list[tuple[str, str, str | None]] = (
    LIBRARY_PURGE + HOSPITAL_PURGE + GENERIC_PURGE + CROSS_SLUG_PURGE
)


def main() -> None:
    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        for from_slug, filt, to_slug in ALL_RULES:
            sql = (
                "UPDATE places SET category = %s "
                f"WHERE category = %s AND ({filt})"
            )
            cur.execute(sql, (to_slug, from_slug))
            moved = cur.rowcount or 0
            target = to_slug if to_slug is not None else "NULL"
            if moved:
                print(f"  {from_slug:<10} → {target:<10}  {moved:>5} rows")
        conn.commit()

        print("\nFinal counts:")
        cur.execute(
            "SELECT category, COUNT(*) FROM places WHERE category IS NOT NULL "
            "GROUP BY 1 ORDER BY 2 DESC"
        )
        for slug, n in cur.fetchall():
            print(f"  {slug:<14} {n:>5}")


if __name__ == "__main__":
    main()
