"""V2 Phase 10: automatic knowledge-conflict detection

Revision ID: 0035
Revises: 0034
"""
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE knowledge_conflicts ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "article_a_id uuid NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE, "
        "article_b_id uuid REFERENCES knowledge_base(id) ON DELETE CASCADE, "
        "dedup_key varchar(160) NOT NULL, conflict_type varchar(40) NOT NULL, severity varchar(20) NOT NULL, "
        "evidence_excerpt_a text NOT NULL, evidence_excerpt_b text, confidence numeric(6,4), sample_size integer, "
        "affected_ticket_ids jsonb NOT NULL DEFAULT '[]'::jsonb, review_state varchar(20) NOT NULL DEFAULT 'open', "
        "resolved_by uuid REFERENCES users(id) ON DELETE SET NULL, resolved_at timestamptz, resolution_note text, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_knowledge_conflict_dedup UNIQUE(tenant_id, dedup_key), "
        "CONSTRAINT ck_knowledge_conflicts_type CHECK(conflict_type IN ('contradictory_steps','low_customer_success','high_engineer_edit_rate','high_reopen_rate','unused_long_period')), "
        "CONSTRAINT ck_knowledge_conflicts_severity CHECK(severity IN ('low','medium','high','critical')), "
        "CONSTRAINT ck_knowledge_conflicts_review_state CHECK(review_state IN ('open','reviewing','resolved','dismissed')))",
        "CREATE INDEX ix_knowledge_conflicts_tenant_id ON knowledge_conflicts(tenant_id, review_state)",
        "CREATE INDEX ix_knowledge_conflicts_article_a ON knowledge_conflicts(article_a_id)",
        "CREATE INDEX ix_knowledge_conflicts_article_b ON knowledge_conflicts(article_b_id)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("knowledge_conflict:read", "knowledge_conflict:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('knowledge_conflict:read','knowledge_conflict:manage')) "
        "OR (r.name='knowledge_manager' AND p.code IN ('knowledge_conflict:read','knowledge_conflict:manage')) "
        "OR (r.name='team_lead' AND p.code = 'knowledge_conflict:read') "
        "OR (r.name='auditor' AND p.code = 'knowledge_conflict:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_conflicts")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('knowledge_conflict:read','knowledge_conflict:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('knowledge_conflict:read','knowledge_conflict:manage')")
