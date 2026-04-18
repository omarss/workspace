"""api_usage table — per-key per-endpoint daily counters

Revision ID: 0011_api_usage
Revises: 0010_ar_ta_marbuta
Create Date: 2026-04-18
"""
from alembic import op

revision = "0011_api_usage"
down_revision = "0010_ar_ta_marbuta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per (key_prefix, endpoint, status_bucket, day). A single
    # UPSERT from the middleware bumps the counter and stamps last_seen.
    # We store a short prefix of the SHA-256 hash of the key — enough
    # to tell requests apart in the admin view without persisting the
    # plaintext secret anywhere.
    op.execute("""
    CREATE TABLE api_usage (
        key_prefix   TEXT    NOT NULL,   -- first 8 hex chars of sha256(key)
        endpoint     TEXT    NOT NULL,   -- e.g. "/v1/places"
        status_bucket INTEGER NOT NULL,  -- 200, 400, 401, 500 (rounded)
        day          DATE    NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')::date,
        count        BIGINT  NOT NULL DEFAULT 0,
        last_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (key_prefix, endpoint, status_bucket, day)
    );
    """)
    op.execute("CREATE INDEX api_usage_day ON api_usage (day DESC);")
    op.execute("CREATE INDEX api_usage_last_seen ON api_usage (last_seen DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_usage;")
