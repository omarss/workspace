"""add english columns to places

Revision ID: 0003_english_columns
Revises: 0002_bilingual_queries
Create Date: 2026-04-18
"""
from alembic import op

revision = "0003_english_columns"
down_revision = "0002_bilingual_queries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `name`/`full_address` hold what Google returned under hl=ar.
    # `name_en`/`full_address_en` hold the hl=en equivalents populated
    # by the English search pass. Both live side-by-side so the API
    # can surface whichever language the client asked for without a
    # second round-trip.
    op.execute("ALTER TABLE places ADD COLUMN name_en TEXT;")
    op.execute("ALTER TABLE places ADD COLUMN full_address_en TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE places DROP COLUMN full_address_en;")
    op.execute("ALTER TABLE places DROP COLUMN name_en;")
