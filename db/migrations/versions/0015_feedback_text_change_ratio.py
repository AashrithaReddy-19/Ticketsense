"""record how much reviewer-edited text changed, for confidence-model retraining

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feedback ADD COLUMN text_change_ratio double precision")


def downgrade() -> None:
    op.execute("ALTER TABLE feedback DROP COLUMN IF EXISTS text_change_ratio")
