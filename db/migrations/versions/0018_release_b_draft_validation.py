"""persist Release B validation for immutable response versions

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("response_drafts", sa.Column("citation_validation_status", sa.String(30), nullable=True))
    op.add_column("response_drafts", sa.Column("validation_details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("claim_validations", sa.Column("response_draft_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_claim_validations_response_draft", "claim_validations", "response_drafts", ["response_draft_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_claim_validations_response_draft_id", "claim_validations", ["response_draft_id"])


def downgrade() -> None:
    op.drop_index("ix_claim_validations_response_draft_id", table_name="claim_validations")
    op.drop_constraint("fk_claim_validations_response_draft", "claim_validations", type_="foreignkey")
    op.drop_column("claim_validations", "response_draft_id")
    op.drop_column("response_drafts", "validation_details")
    op.drop_column("response_drafts", "citation_validation_status")
