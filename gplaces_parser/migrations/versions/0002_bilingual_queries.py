"""add query column to scrape_jobs for bilingual search

Revision ID: 0002_bilingual_queries
Revises: 0001_initial
Create Date: 2026-04-18
"""
from alembic import op

revision = "0002_bilingual_queries"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Each (category, tile) is now scraped once per language — a tile × coffee
    # fires for both "مقاهي" and "coffee shops". The unique index widens to
    # include the query text so the two rows can coexist without CONFLICT.
    op.execute("ALTER TABLE scrape_jobs ADD COLUMN query TEXT;")
    op.execute("DROP INDEX IF EXISTS scrape_jobs_places_uniq;")
    op.execute("""
    CREATE UNIQUE INDEX scrape_jobs_places_uniq
        ON scrape_jobs (category, tile_lat, tile_lng, COALESCE(query, ''))
        WHERE kind = 'places';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS scrape_jobs_places_uniq;")
    op.execute("""
    CREATE UNIQUE INDEX scrape_jobs_places_uniq
        ON scrape_jobs (category, tile_lat, tile_lng)
        WHERE kind = 'places';
    """)
    op.execute("ALTER TABLE scrape_jobs DROP COLUMN query;")
