"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-17
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE places (
        place_id         TEXT PRIMARY KEY,
        google_id        TEXT,
        cid              TEXT,
        name             TEXT NOT NULL,
        full_address     TEXT,
        borough          TEXT,
        street           TEXT,
        city             TEXT,
        postal_code      TEXT,
        country          TEXT,
        latitude         DOUBLE PRECISION,
        longitude        DOUBLE PRECISION,
        phone            TEXT,
        website          TEXT,
        rating           NUMERIC(2,1),
        reviews_count    INTEGER,
        reviews_per_score JSONB,   -- {"1": n, "2": n, ... "5": n}
        photos_count     INTEGER,
        price_level      TEXT,
        category         TEXT NOT NULL,
        subcategories    TEXT[],
        working_hours    JSONB,
        popular_times    JSONB,
        plus_code        TEXT,
        bounds           JSONB,   -- bounding box / viewport if returned
        service_area     JSONB,   -- service-area polygon(s) for mobile businesses
        verified         BOOLEAN,
        business_status  TEXT,
        google_url       TEXT,
        query            TEXT,
        tile_lat         DOUBLE PRECISION,
        tile_lng         DOUBLE PRECISION,
        raw              JSONB NOT NULL,
        reviews_scraped_at TIMESTAMPTZ,
        scraped_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX places_category_idx ON places (category);")
    op.execute("CREATE INDEX places_geo_idx ON places (latitude, longitude);")
    op.execute("CREATE INDEX places_reviews_count_idx ON places (reviews_count DESC);")
    op.execute("CREATE INDEX places_reviews_scraped_idx ON places (reviews_scraped_at NULLS FIRST);")

    op.execute("""
    CREATE TABLE reviews (
        review_id            TEXT PRIMARY KEY,
        place_id             TEXT NOT NULL REFERENCES places(place_id) ON DELETE CASCADE,
        author_title         TEXT,
        author_id            TEXT,
        author_url           TEXT,
        author_reviews_count INTEGER,
        author_ratings_count INTEGER,
        rating               INTEGER,
        text                 TEXT,
        text_translated      TEXT,
        language             TEXT,
        published_at         TIMESTAMPTZ,
        likes                INTEGER,
        owner_answer         TEXT,
        owner_answer_at      TIMESTAMPTZ,
        photos               JSONB,   -- [{"url": "...", "width": w, "height": h}, ...]
        raw                  JSONB NOT NULL,
        scraped_at           TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX reviews_place_idx ON reviews (place_id);")
    op.execute("CREATE INDEX reviews_published_idx ON reviews (published_at DESC NULLS LAST);")
    op.execute("CREATE INDEX reviews_rating_idx ON reviews (rating);")

    # Resumable job log — one row per (kind, scope key).
    op.execute("""
    CREATE TABLE scrape_jobs (
        id                    BIGSERIAL PRIMARY KEY,
        kind                  TEXT NOT NULL CHECK (kind IN ('places','reviews')),
        category              TEXT,
        tile_lat              DOUBLE PRECISION,
        tile_lng              DOUBLE PRECISION,
        place_id              TEXT,
        status                TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','running','completed','failed','skipped')),
        outscraper_request_id TEXT,
        results_count         INTEGER DEFAULT 0,
        error                 TEXT,
        attempts              INTEGER NOT NULL DEFAULT 0,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
        started_at            TIMESTAMPTZ,
        finished_at           TIMESTAMPTZ
    );
    """)
    op.execute("CREATE INDEX scrape_jobs_status_idx ON scrape_jobs (kind, status);")
    op.execute("""
    CREATE UNIQUE INDEX scrape_jobs_places_uniq
        ON scrape_jobs (category, tile_lat, tile_lng)
        WHERE kind = 'places';
    """)
    op.execute("""
    CREATE UNIQUE INDEX scrape_jobs_reviews_uniq
        ON scrape_jobs (place_id)
        WHERE kind = 'reviews';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scrape_jobs;")
    op.execute("DROP TABLE IF EXISTS reviews;")
    op.execute("DROP TABLE IF EXISTS places;")
