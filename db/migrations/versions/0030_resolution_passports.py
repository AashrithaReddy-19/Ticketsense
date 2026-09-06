"""V2 Phase 5: immutable Resolution Passport

Revision ID: 0030
Revises: 0029
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE resolution_passports ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), schema_version integer NOT NULL DEFAULT 1, "
        "tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "department_id uuid REFERENCES departments(id) ON DELETE SET NULL, "
        "ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, "
        "resolution_type varchar(20) NOT NULL, is_current boolean NOT NULL DEFAULT true, "
        "is_backfilled boolean NOT NULL DEFAULT false, "
        "supersedes_passport_id uuid REFERENCES resolution_passports(id) ON DELETE SET NULL, "
        "previous_passport_hash varchar(64), "
        "input_content_hash varchar(64), classification_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb, "
        "pipeline_execution_id uuid REFERENCES pipeline_executions(id) ON DELETE SET NULL, "
        "ticket_decision_id uuid REFERENCES ticket_decisions(id) ON DELETE SET NULL, "
        "response_draft_id uuid REFERENCES response_drafts(id) ON DELETE SET NULL, "
        "response_version_number integer, response_content_hash varchar(64), "
        "citations jsonb NOT NULL DEFAULT '[]'::jsonb, claim_validations jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "confidence_components jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "overall_confidence numeric(6,4), applicable_threshold numeric(6,4), "
        "passed_gates jsonb NOT NULL DEFAULT '[]'::jsonb, failed_gates jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "policy_id uuid REFERENCES department_resolution_policies(id) ON DELETE SET NULL, policy_version integer, "
        "engineer_edit_ratio numeric(6,4), feedback_id uuid REFERENCES feedback(id) ON DELETE SET NULL, "
        "reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL, author_user_id uuid REFERENCES users(id) ON DELETE SET NULL, "
        "integrity_hash varchar(64) NOT NULL, created_by uuid NOT NULL REFERENCES users(id), "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT ck_resolution_passports_type CHECK(resolution_type IN ('ai','engineer')))",
        "CREATE INDEX ix_resolution_passports_tenant_id ON resolution_passports(tenant_id)",
        "CREATE INDEX ix_resolution_passports_department_id ON resolution_passports(department_id)",
        "CREATE INDEX ix_resolution_passports_ticket_id ON resolution_passports(ticket_id)",
        "CREATE UNIQUE INDEX uq_resolution_passports_current ON resolution_passports(ticket_id) WHERE is_current",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("passport:read", "passport:export", "passport:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('passport:read','passport:export','passport:manage')) "
        "OR (r.name='support_agent' AND p.code = 'passport:read') "
        "OR (r.name='reviewer' AND p.code = 'passport:read') "
        "OR (r.name='team_lead' AND p.code IN ('passport:read','passport:export')) "
        "OR (r.name='auditor' AND p.code IN ('passport:read','passport:export')) "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS resolution_passports")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('passport:read','passport:export','passport:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('passport:read','passport:export','passport:manage')")
