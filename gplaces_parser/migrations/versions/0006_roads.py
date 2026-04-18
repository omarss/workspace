"""add roads table for /v1/roads endpoint

Revision ID: 0006_roads
Revises: 0005_status_and_history
Create Date: 2026-04-18
"""
from alembic import op

revision = "0006_roads"
down_revision = "0005_status_and_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Roads are fed from the external `maps/roads.json` build artifact by
    # `scripts/load_roads.py`. We store the polygon as JSONB (no PostGIS
    # available locally) and expose a pre-computed bounding box on each
    # row so the `/v1/roads` query can do an index-backed prefilter
    # before doing the expensive shapely point-in-polygon test.
    op.execute("""
    CREATE TABLE roads (
        osm_id            BIGINT PRIMARY KEY,
        name              TEXT,
        name_en           TEXT,
        highway           TEXT NOT NULL,
        ref               TEXT,
        maxspeed_kmh      INTEGER NOT NULL,
        speed_source      TEXT,
        speed_confidence  REAL,
        lanes             INTEGER,
        width_m           REAL,
        oneway            BOOLEAN,
        bbox_min_lat      DOUBLE PRECISION NOT NULL,
        bbox_max_lat      DOUBLE PRECISION NOT NULL,
        bbox_min_lon      DOUBLE PRECISION NOT NULL,
        bbox_max_lon      DOUBLE PRECISION NOT NULL,
        geom              JSONB NOT NULL,
        loaded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    # Points are looked up by (lat, lon) against a bbox. A composite index
    # on (bbox_min_lat, bbox_max_lat) is useful, but the query plan is
    # usually driven by the tighter of the two ranges, so we index both
    # axes separately and let Postgres pick.
    op.execute("CREATE INDEX roads_bbox_lat ON roads (bbox_min_lat, bbox_max_lat);")
    op.execute("CREATE INDEX roads_bbox_lon ON roads (bbox_min_lon, bbox_max_lon);")
    op.execute("CREATE INDEX roads_highway ON roads (highway);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS roads;")
