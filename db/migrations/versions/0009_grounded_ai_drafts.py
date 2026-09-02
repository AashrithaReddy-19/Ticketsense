"""grounded AI draft persistence

Revision ID: 0009
Revises: 0008
"""
from alembic import op
revision="0009"; down_revision="0008"; branch_labels=None; depends_on=None

def upgrade()->None:
    op.execute("""CREATE TABLE ai_drafts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES organizations(id),ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,department_id uuid NOT NULL REFERENCES departments(id),article_version varchar(20) NOT NULL DEFAULT '1.0',draft_text text,citations jsonb NOT NULL DEFAULT '[]',evidence jsonb NOT NULL DEFAULT '[]',provider varchar(80),model varchar(120),generation_status varchar(40) NOT NULL DEFAULT 'pending',citation_validation_status varchar(40) NOT NULL DEFAULT 'pending',validation_details jsonb NOT NULL DEFAULT '{}',generation_error text,insufficient_evidence boolean NOT NULL DEFAULT false,attempt_count integer NOT NULL DEFAULT 1,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),CONSTRAINT uq_ai_drafts_ticket UNIQUE(ticket_id))""")
    op.execute("CREATE INDEX ix_ai_drafts_scope ON ai_drafts(tenant_id,department_id,ticket_id)")

def downgrade()->None:
    op.execute("DROP INDEX IF EXISTS ix_ai_drafts_scope")
    op.execute("DROP TABLE IF EXISTS ai_drafts")
