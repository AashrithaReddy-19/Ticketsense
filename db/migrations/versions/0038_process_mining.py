"""V2 Phase 14: process mining (real event-history variants and bottlenecks)

Revision ID: 0038
Revises: 0037
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE process_mining_runs ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "status varchar(20) NOT NULL, ticket_count_considered integer NOT NULL DEFAULT 0, "
        "event_count_considered integer NOT NULL DEFAULT 0, "
        "variants jsonb NOT NULL DEFAULT '[]'::jsonb, bottlenecks jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "insufficiency_reason text, started_at timestamptz NOT NULL, completed_at timestamptz, "
        "created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT ck_process_mining_runs_status CHECK(status IN ('completed','insufficient_data')))",
        "CREATE INDEX ix_process_mining_runs_tenant_id ON process_mining_runs(tenant_id, created_at DESC)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("process_mining:read", "process_mining:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('process_mining:read','process_mining:manage')) "
        "OR (r.name='team_lead' AND p.code = 'process_mining:read') "
        "OR (r.name='auditor' AND p.code = 'process_mining:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS process_mining_runs")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('process_mining:read','process_mining:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('process_mining:read','process_mining:manage')")
