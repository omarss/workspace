"""widen question_options letter set from A–D to A–H

Revision ID: 0002_eight_options
Revises: 0001_initial
Create Date: 2026-04-20
"""
from alembic import op

revision = "0002_eight_options"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eight options per question — one correct, seven distractors. The
    # letter in the DB is stable; the API re-shuffles + re-letters on
    # every retrieval so consumers never see two requests with the same
    # option order.
    op.execute("ALTER TABLE question_options DROP CONSTRAINT question_options_letter_check;")
    op.execute(
        "ALTER TABLE question_options ADD CONSTRAINT question_options_letter_check "
        "CHECK (letter IN ('A','B','C','D','E','F','G','H'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE question_options DROP CONSTRAINT question_options_letter_check;")
    op.execute(
        "ALTER TABLE question_options ADD CONSTRAINT question_options_letter_check "
        "CHECK (letter IN ('A','B','C','D'));"
    )
