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
    ("library", "subcategories[1] ~* 'electronics|bookstore|book store|stationery|office supplies' OR subcategories[1] ~ 'متجر|قرطاسية|أدوات مكتبية'", "bookstore"),
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

ALL_RULES: list[tuple[str, str, str | None]] = LIBRARY_PURGE + HOSPITAL_PURGE


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
