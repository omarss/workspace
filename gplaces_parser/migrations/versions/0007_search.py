"""search index (tsvector + trigram, trigger-maintained)

Revision ID: 0007_search
Revises: 0006_roads
Create Date: 2026-04-18
"""
from alembic import op

revision = "0007_search"
down_revision = "0006_roads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Trigram search handles typos and partial matches in both Arabic and
    # English — the 'simple' FTS config doesn't stem (there's no Arabic
    # dictionary shipped with pg 18), so trigram fills the "typos / partial
    # word" gap that FTS leaves behind.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # Plain column + trigger instead of a generated column because
    # `to_tsvector('simple', ...)` is classified as non-immutable when the
    # config is passed as a literal, which rules out GENERATED STORED.
    op.execute("ALTER TABLE places ADD COLUMN search_tsv tsvector;")

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
    CREATE TRIGGER places_tsv_update
      BEFORE INSERT OR UPDATE OF name, name_en, category, subcategories,
                                 full_address, full_address_en
      ON places
      FOR EACH ROW EXECUTE FUNCTION places_tsv_refresh();
    """)

    # Backfill the column for existing rows. A plain `UPDATE places SET
    # search_tsv = <expr>` would work but firing a self-update with a
    # no-op column forces the trigger to run and keeps the expression
    # in one place (the trigger function).
    op.execute("UPDATE places SET name = name;")

    op.execute("CREATE INDEX places_search_tsv ON places USING GIN (search_tsv);")

    # Trigram indexes on the two name columns. We skip address trigrams —
    # they're noisy (every "Riyadh 11564" collides) and the FTS column
    # already catches address tokens.
    op.execute("CREATE INDEX places_name_trgm ON places USING GIN (name gin_trgm_ops);")
    op.execute("CREATE INDEX places_name_en_trgm ON places USING GIN (name_en gin_trgm_ops);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS places_name_en_trgm;")
    op.execute("DROP INDEX IF EXISTS places_name_trgm;")
    op.execute("DROP INDEX IF EXISTS places_search_tsv;")
    op.execute("DROP TRIGGER IF EXISTS places_tsv_update ON places;")
    op.execute("DROP FUNCTION IF EXISTS places_tsv_refresh();")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS search_tsv;")
