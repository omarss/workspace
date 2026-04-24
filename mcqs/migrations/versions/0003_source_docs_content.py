"""store full source-doc text so the omono /v1/mcq/docs endpoints can
serve the original markdown without reconstructing from chunks.

Chunks drop the heading line itself (it lives in heading_path) and
windowed sections overlap by mcqs_chunk_overlap tokens, so reassembling
the original from doc_chunks is lossy. A single column on source_docs
keeps the serving surface trivial and stores the authoritative text
exactly once per file.

Revision ID: 0003_source_docs_content
Revises: 0002_eight_options
Create Date: 2026-04-24
"""
from alembic import op

revision = "0003_source_docs_content"
down_revision = "0002_eight_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable so the migration is non-blocking on a large table; ingest
    # backfills the column on its next pass (and also writes every new
    # ingest going forward).
    op.execute("ALTER TABLE source_docs ADD COLUMN content_text TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE source_docs DROP COLUMN content_text;")
