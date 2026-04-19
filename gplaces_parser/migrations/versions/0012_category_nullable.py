"""allow places.category to be NULL

Revision ID: 0012_category_nullable
Revises: 0011_api_usage
Create Date: 2026-04-19

When a place was originally scraped under category X and later human
review decides X is wrong, we need somewhere to put it that isn't
wrong — NULL is the correct signal for "we don't confidently classify
this". The API filter already handles nulls (they won't match any
`category=...` query).
"""
from alembic import op

revision = "0012_category_nullable"
down_revision = "0011_api_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE places ALTER COLUMN category DROP NOT NULL;")


def downgrade() -> None:
    # Force non-null only if every row has a category; otherwise the
    # downgrade fails loudly (safer than silently injecting a default).
    op.execute("ALTER TABLE places ALTER COLUMN category SET NOT NULL;")
