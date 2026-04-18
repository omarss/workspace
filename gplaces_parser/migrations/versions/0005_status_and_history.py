"""business status + opening-hours + rating/status history

Revision ID: 0005_status_and_history
Revises: 0004_name_nullable
Create Date: 2026-04-18
"""
from alembic import op

revision = "0005_status_and_history"
down_revision = "0004_name_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns on `places`. `business_status` already existed but was
    # never populated — now it's the canonical OPERATIONAL / CLOSED_*
    # flag. `hours_snippet` is the one-liner off the card ("Closes 10 PM"),
    # `working_hours` stays JSONB with a per-day schedule from pass 2.
    op.execute("ALTER TABLE places ADD COLUMN open_now BOOLEAN;")
    op.execute("ALTER TABLE places ADD COLUMN hours_snippet TEXT;")
    op.execute("ALTER TABLE places ADD COLUMN status_updated_at TIMESTAMPTZ;")

    # Append-only history — one row per scrape per place. Queries like
    # "how did rating change over the last 6 months" just ORDER BY captured_at.
    op.execute("""
    CREATE TABLE rating_history (
        id             BIGSERIAL PRIMARY KEY,
        place_id       TEXT NOT NULL REFERENCES places(place_id) ON DELETE CASCADE,
        rating         NUMERIC(2,1),
        reviews_count  INTEGER,
        captured_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX rating_history_place_time ON rating_history (place_id, captured_at DESC);")

    op.execute("""
    CREATE TABLE status_history (
        id              BIGSERIAL PRIMARY KEY,
        place_id        TEXT NOT NULL REFERENCES places(place_id) ON DELETE CASCADE,
        business_status TEXT,         -- OPERATIONAL / CLOSED_TEMPORARILY / CLOSED_PERMANENTLY
        open_now        BOOLEAN,
        hours_snippet   TEXT,
        working_hours   JSONB,
        captured_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX status_history_place_time ON status_history (place_id, captured_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS status_history;")
    op.execute("DROP TABLE IF EXISTS rating_history;")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS status_updated_at;")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS hours_snippet;")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS open_now;")
