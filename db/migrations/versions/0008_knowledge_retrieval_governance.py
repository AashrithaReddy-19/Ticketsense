"""knowledge retrieval governance metadata

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_base ADD COLUMN status varchar(30) NOT NULL DEFAULT 'approved'")
    op.execute("ALTER TABLE knowledge_base ADD COLUMN version varchar(20) NOT NULL DEFAULT '1.0'")
    op.execute("ALTER TABLE knowledge_base ADD COLUMN is_publishable boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE knowledge_base ADD CONSTRAINT ck_knowledge_base_status CHECK (status IN ('draft', 'approved', 'archived'))")
    op.execute("CREATE INDEX ix_knowledge_base_retrieval_scope ON knowledge_base (tenant_id, department_id, status, version) WHERE is_publishable = true")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_base_retrieval_scope")
    op.execute("ALTER TABLE knowledge_base DROP CONSTRAINT IF EXISTS ck_knowledge_base_status")
    op.drop_column("knowledge_base", "is_publishable")
    op.drop_column("knowledge_base", "version")
    op.drop_column("knowledge_base", "status")
