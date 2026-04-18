"""ar_normalize: also fold ta-marbuta (ة) to ha (ه)

Revision ID: 0010_ar_ta_marbuta
Revises: 0009_ar_normalize
Create Date: 2026-04-18

Saudi users frequently type `قهوه` instead of the formal `قهوة`, and
the same for every ta-marbuta-ending noun. Folding ة → ه in the
normalizer makes both spellings hit the same tsvector token. Mirror
the change in `search_synonyms._AR_FOLD` on the app side.
"""
from alembic import op

revision = "0010_ar_ta_marbuta"
down_revision = "0009_ar_normalize"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE OR REPLACE FUNCTION ar_normalize(txt text) RETURNS text
    LANGUAGE SQL
    IMMUTABLE
    PARALLEL SAFE
    AS $$
      SELECT translate(
        regexp_replace(
          COALESCE(txt, ''),
          '[' || chr(1611) || '-' || chr(1631) || chr(1648) || chr(1600) || ']',
          '',
          'g'
        ),
        'أإآٱىة',
        'اااييه'
      );
    $$;
    """)
    op.execute("UPDATE places SET name = name;")
    op.execute("UPDATE reviews SET text = text;")


def downgrade() -> None:
    op.execute(r"""
    CREATE OR REPLACE FUNCTION ar_normalize(txt text) RETURNS text
    LANGUAGE SQL
    IMMUTABLE
    PARALLEL SAFE
    AS $$
      SELECT translate(
        regexp_replace(
          COALESCE(txt, ''),
          '[' || chr(1611) || '-' || chr(1631) || chr(1648) || chr(1600) || ']',
          '',
          'g'
        ),
        'أإآٱى',
        'اااي' || 'ي'
      );
    $$;
    """)
    op.execute("UPDATE places SET name = name;")
    op.execute("UPDATE reviews SET text = text;")
