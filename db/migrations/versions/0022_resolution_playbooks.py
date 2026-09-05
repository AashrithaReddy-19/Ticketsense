"""Section 13: versioned smart resolution playbooks

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE playbooks ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,"
        " playbook_key varchar(80) NOT NULL,"
        " title varchar(255) NOT NULL,"
        " category varchar(120) NOT NULL,"
        " version integer NOT NULL,"
        " status varchar(20) NOT NULL DEFAULT 'draft',"
        " applicable_error_codes jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " clarification_questions jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " evidence_requirements jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " diagnostic_steps_template jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " approved_actions jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " safety_warnings jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " resolution_template text,"
        " escalation_rules jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " auto_resolution_eligible boolean NOT NULL DEFAULT false,"
        " superseded_by_id uuid REFERENCES playbooks(id) ON DELETE SET NULL,"
        " created_by uuid NOT NULL REFERENCES users(id),"
        " approved_by uuid REFERENCES users(id),"
        " reason text,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_playbook_key_version UNIQUE(tenant_id, playbook_key, version),"
        " CONSTRAINT ck_playbooks_status CHECK (status IN ('draft','approved','active','inactive','superseded'))"
        ")",
        "CREATE INDEX ix_playbooks_tenant_id ON playbooks(tenant_id)",
        "CREATE INDEX ix_playbooks_scope ON playbooks(tenant_id, category, status)",
        "CREATE INDEX ix_playbooks_key ON playbooks(tenant_id, playbook_key, status)",
        "CREATE TABLE playbook_applications ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,"
        " playbook_id uuid NOT NULL REFERENCES playbooks(id) ON DELETE CASCADE,"
        " ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,"
        " diagnostic_plan_id uuid REFERENCES diagnostic_plans(id) ON DELETE SET NULL,"
        " applied_by uuid REFERENCES users(id),"
        " application_type varchar(20) NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT ck_playbook_applications_type CHECK (application_type IN ('recommended','applied'))"
        ")",
        "CREATE INDEX ix_playbook_applications_ticket ON playbook_applications(tenant_id, ticket_id, created_at DESC)",
        "CREATE INDEX ix_playbook_applications_playbook ON playbook_applications(playbook_id)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("playbook:manage",)
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE p.code='playbook:manage' AND r.name IN ('system_admin','team_lead') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS playbook_applications")
    op.execute("DROP TABLE IF EXISTS playbooks")
