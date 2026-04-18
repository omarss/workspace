"""relax places.name NOT NULL for english-only discoveries

Revision ID: 0004_name_nullable
Revises: 0003_english_columns
Create Date: 2026-04-18
"""
from alembic import op

revision = "0004_name_nullable"
down_revision = "0003_english_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A place first surfaced by an English-language search only has its
    # `name_en` populated (the hl=ar pass for that same place hasn't run
    # yet), so `name` arrives NULL. Keep a light check that *some* name
    # field is present via a partial check constraint rather than forcing
    # both languages on every row.
    op.execute("ALTER TABLE places ALTER COLUMN name DROP NOT NULL;")
    op.execute("""
    ALTER TABLE places
      ADD CONSTRAINT places_has_a_name
      CHECK (name IS NOT NULL OR name_en IS NOT NULL);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE places DROP CONSTRAINT IF EXISTS places_has_a_name;")
    op.execute("ALTER TABLE places ALTER COLUMN name SET NOT NULL;")
