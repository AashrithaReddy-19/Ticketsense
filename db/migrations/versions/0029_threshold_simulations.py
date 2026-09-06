"""V2 Phase 4: adaptive threshold simulation (read-only, never auto-deployed)

Revision ID: 0029
Revises: 0028
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE threshold_simulations (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, department_id uuid REFERENCES departments(id) ON DELETE SET NULL, category varchar(120), proposed_threshold numeric(4,3) NOT NULL, sample_size integer NOT NULL, auto_resolved_at_threshold integer NOT NULL, data_sufficient boolean NOT NULL, insufficiency_reasons jsonb NOT NULL DEFAULT '[]'::jsonb, estimated_coverage numeric(6,4), estimated_referral_rate numeric(6,4), historical_false_resolution_rate numeric(6,4), confidence_interval_low numeric(6,4), confidence_interval_high numeric(6,4), sensitive_category_override boolean NOT NULL DEFAULT false, based_on varchar(40) NOT NULL DEFAULT 'ticket_decisions', created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_threshold_simulations_threshold CHECK(proposed_threshold BETWEEN 0 AND 1))",
        "CREATE INDEX ix_threshold_simulations_scope ON threshold_simulations(tenant_id,department_id,category,created_at DESC)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("threshold:read", "threshold:simulate")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('threshold:read','threshold:simulate')) "
        "OR (r.name='team_lead' AND p.code = 'threshold:read') "
        "OR (r.name='auditor' AND p.code = 'threshold:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS threshold_simulations")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('threshold:read','threshold:simulate'))")
    op.execute("DELETE FROM permissions WHERE code IN ('threshold:read','threshold:simulate')")
