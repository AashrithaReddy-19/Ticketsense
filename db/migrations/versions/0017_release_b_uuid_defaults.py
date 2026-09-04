"""align Release B primary keys with UUIDPKMixin server defaults

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("pipeline_executions", "pipeline_stages", "technical_entities", "claim_validations"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT gen_random_uuid()")


def downgrade() -> None:
    for table in ("pipeline_executions", "pipeline_stages", "technical_entities", "claim_validations"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
