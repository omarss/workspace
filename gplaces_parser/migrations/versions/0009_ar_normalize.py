"""Arabic normalization + re-indexed tsvectors

Revision ID: 0009_ar_normalize
Revises: 0008_reviews_fts
Create Date: 2026-04-18

Strip harakat / tatweel and fold Alef variants, Ya-Maqsura so search
matches across the orthographic variants Arabic users type. Applied
immutably so the places/reviews tsvectors can be rebuilt around it.
"""
from alembic import op

revision = "0009_ar_normalize"
down_revision = "0008_reviews_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Arabic has several orthographic variants that Google, OSM, and users
    # treat as the same word:
    #
    #   أ إ آ ٱ  → ا        ("alef with hamza" variants → plain alef)
    #   ى        → ي        (alef-maqsura → ya)
    #   harakat  → ""       (U+064B..U+065F, U+0670 — diacritic marks)
    #   tatweel  → ""       (U+0640 — decorative stretcher)
    #
    # Keeping ة (ta-marbuta) and ه (ha) distinct — they're phonemically
    # different and most users type them correctly.
    #
    # Must be IMMUTABLE to be usable inside tsvector triggers and the
    # generated-column-style index expressions we want below.
    op.execute(r"""
    CREATE OR REPLACE FUNCTION ar_normalize(txt text) RETURNS text
    LANGUAGE SQL
    IMMUTABLE
    PARALLEL SAFE
    AS $$
      SELECT translate(
        regexp_replace(
          COALESCE(txt, ''),
          '[' || chr(1611) || '-' || chr(1631) || chr(1648) || chr(1600) || ']',
          '',
          'g'
        ),
        'أإآٱى',
        'اااي' || 'ي'
      );
    $$;
    """)

    # Rebuild the places trigger to wrap every COALESCE(col, '') in ar_normalize.
    op.execute("""
    CREATE OR REPLACE FUNCTION places_tsv_refresh() RETURNS trigger AS $$
    BEGIN
      NEW.search_tsv :=
        setweight(to_tsvector('simple', ar_normalize(NEW.name)), 'A') ||
        setweight(to_tsvector('simple', ar_normalize(NEW.name_en)), 'A') ||
        setweight(to_tsvector('simple', ar_normalize(NEW.category)), 'B') ||
        setweight(to_tsvector('simple',
          ar_normalize(array_to_string(NEW.subcategories, ' '))), 'B') ||
        setweight(to_tsvector('simple', ar_normalize(NEW.full_address)), 'C') ||
        setweight(to_tsvector('simple', ar_normalize(NEW.full_address_en)), 'C');
      RETURN NEW;
    END
    $$ LANGUAGE plpgsql;
    """)

    # Same for reviews.
    op.execute("""
    CREATE OR REPLACE FUNCTION reviews_tsv_refresh() RETURNS trigger AS $$
    BEGIN
      NEW.search_tsv := to_tsvector('simple', ar_normalize(NEW.text));
      RETURN NEW;
    END
    $$ LANGUAGE plpgsql;
    """)

    # Backfill existing rows so the stored tsvectors reflect the new norm.
    op.execute("UPDATE places SET name = name;")
    op.execute("UPDATE reviews SET text = text;")


def downgrade() -> None:
    # Restore pre-normalization trigger bodies. ar_normalize stays — dropping
    # the function would force us to reset every call site simultaneously,
    # and leaving it costs nothing if unused.
    op.execute("""
    CREATE OR REPLACE FUNCTION places_tsv_refresh() RETURNS trigger AS $$
    BEGIN
      NEW.search_tsv :=
        setweight(to_tsvector('simple', COALESCE(NEW.name, '')), 'A') ||
        setweight(to_tsvector('simple', COALESCE(NEW.name_en, '')), 'A') ||
        setweight(to_tsvector('simple', COALESCE(NEW.category, '')), 'B') ||
        setweight(to_tsvector('simple',
          COALESCE(array_to_string(NEW.subcategories, ' '), '')), 'B') ||
        setweight(to_tsvector('simple', COALESCE(NEW.full_address, '')), 'C') ||
        setweight(to_tsvector('simple', COALESCE(NEW.full_address_en, '')), 'C');
      RETURN NEW;
    END
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION reviews_tsv_refresh() RETURNS trigger AS $$
    BEGIN
      NEW.search_tsv := to_tsvector('simple', COALESCE(NEW.text, ''));
      RETURN NEW;
    END
    $$ LANGUAGE plpgsql;
    """)
    op.execute("UPDATE places SET name = name;")
    op.execute("UPDATE reviews SET text = text;")
