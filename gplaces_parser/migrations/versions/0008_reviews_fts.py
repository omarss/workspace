"""FTS index on reviews.text

Revision ID: 0008_reviews_fts
Revises: 0007_search
Create Date: 2026-04-18
"""
from alembic import op

revision = "0008_reviews_fts"
down_revision = "0007_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Same trigger pattern as places.search_tsv: plain tsvector column +
    # BEFORE trigger keeps it in sync with `text`. We deliberately do NOT
    # add a trigram GIN on review text — review bodies can be paragraphs
    # and trigram GIN scales as O(text length × row count), which is fine
    # for 14k place names but not for tens of thousands of reviews.
    op.execute("ALTER TABLE reviews ADD COLUMN search_tsv tsvector;")

    op.execute("""
    CREATE OR REPLACE FUNCTION reviews_tsv_refresh() RETURNS trigger AS $$
    BEGIN
      -- No weighting: a word appearing in a review has the same relevance
      -- regardless of where; authors don't follow a headline convention.
      NEW.search_tsv := to_tsvector('simple', COALESCE(NEW.text, ''));
      RETURN NEW;
    END
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE TRIGGER reviews_tsv_update
      BEFORE INSERT OR UPDATE OF text ON reviews
      FOR EACH ROW EXECUTE FUNCTION reviews_tsv_refresh();
    """)

    # Backfill existing rows — fires the trigger via a no-op self-update.
    op.execute("UPDATE reviews SET text = text;")

    op.execute("CREATE INDEX reviews_search_tsv ON reviews USING GIN (search_tsv);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS reviews_search_tsv;")
    op.execute("DROP TRIGGER IF EXISTS reviews_tsv_update ON reviews;")
    op.execute("DROP FUNCTION IF EXISTS reviews_tsv_refresh();")
    op.execute("ALTER TABLE reviews DROP COLUMN IF EXISTS search_tsv;")
