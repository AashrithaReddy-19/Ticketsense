"""Section 19: safe, allowlisted action framework

Revision ID: 0024
Revises: 0023
"""
import json

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


# Global action metadata — not tenant-owned. The actual preview/execute logic
# lives in code (app/services/safe_actions.py:REGISTRY), keyed by action_key;
# this is display/policy metadata only.
DEFINITIONS = (
    dict(action_key="check_service_status", display_name="Check service status", category="diagnostics", risk_level="low",
         description="Reports whether a configured integration/connector is enabled. Sandboxed — no real monitoring provider is configured in this environment.",
         parameter_schema={"service_name": {"type": "string", "required": True}},
         requires_confirmation=False, requires_customer_consent=False, connector="sandbox",
         timeout_seconds=10, supports_dry_run=True, supports_rollback=False),
    dict(action_key="resend_verification_notification", display_name="Resend verification notification", category="customer_communication", risk_level="low",
         description="Sends a real in-app verification reminder notification to the customer who submitted the given ticket.",
         parameter_schema={"ticket_id": {"type": "uuid", "required": True}},
         requires_confirmation=True, requires_customer_consent=False, connector="internal",
         timeout_seconds=10, supports_dry_run=True, supports_rollback=False),
    dict(action_key="generate_vpn_configuration_template", display_name="Generate VPN configuration template", category="self_service", risk_level="low",
         description="Generates a generic VPN client configuration template (no real server address, keys, or credentials).",
         parameter_schema={"username": {"type": "string", "required": True}},
         requires_confirmation=False, requires_customer_consent=False, connector="internal",
         timeout_seconds=10, supports_dry_run=True, supports_rollback=False),
    dict(action_key="check_account_lock_status", display_name="Check account lock status", category="account", risk_level="low",
         description="Reports whether an account is currently locked and its failed-login count. Never returns password data.",
         parameter_schema={"email": {"type": "email", "required": True}},
         requires_confirmation=False, requires_customer_consent=False, connector="internal",
         timeout_seconds=10, supports_dry_run=True, supports_rollback=False),
    dict(action_key="create_password_reset_request", display_name="Create password-reset request", category="account", risk_level="high",
         description="Creates an auditable password-reset request notification for the account. Never changes the real password — high risk, requires a second approver.",
         parameter_schema={"email": {"type": "email", "required": True}},
         requires_confirmation=True, requires_customer_consent=True, connector="internal",
         timeout_seconds=10, supports_dry_run=True, supports_rollback=False),
)


def upgrade() -> None:
    statements = [
        # Global capability registry — not tenant-owned. Rows are seeded a few lines
        # down in this same migration (metadata only; the actual preview/execute
        # logic lives in code, keyed by action_key, in app/services/safe_actions.py —
        # this table is never used to decide *what code runs*, only what's
        # enabled/visible/required for it).
        "CREATE TABLE safe_action_definitions ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " action_key varchar(80) NOT NULL UNIQUE,"
        " display_name varchar(255) NOT NULL,"
        " description text NOT NULL,"
        " category varchar(80) NOT NULL,"
        " risk_level varchar(20) NOT NULL,"
        " required_capability varchar(80) NOT NULL DEFAULT 'safe_action:execute',"
        " parameter_schema jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " requires_confirmation boolean NOT NULL DEFAULT true,"
        " requires_customer_consent boolean NOT NULL DEFAULT false,"
        " enabled boolean NOT NULL DEFAULT true,"
        " connector varchar(40) NOT NULL DEFAULT 'internal',"
        " timeout_seconds integer NOT NULL DEFAULT 10,"
        " supports_dry_run boolean NOT NULL DEFAULT true,"
        " supports_rollback boolean NOT NULL DEFAULT false,"
        " tenant_scoped boolean NOT NULL DEFAULT true,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT ck_safe_action_risk CHECK (risk_level IN ('low','medium','high'))"
        ")",
        "CREATE TABLE safe_action_executions ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,"
        " action_key varchar(80) NOT NULL REFERENCES safe_action_definitions(action_key),"
        " ticket_id uuid REFERENCES tickets(id) ON DELETE SET NULL,"
        " department_id uuid REFERENCES departments(id) ON DELETE SET NULL,"
        " requested_by uuid NOT NULL REFERENCES users(id),"
        " parameters jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " mode varchar(20) NOT NULL DEFAULT 'execute',"
        " status varchar(30) NOT NULL DEFAULT 'pending',"
        " requires_approval boolean NOT NULL DEFAULT false,"
        " idempotency_key varchar(120),"
        " error_summary text,"
        " started_at timestamptz,"
        " completed_at timestamptz,"
        " duration_ms integer,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT ck_safe_action_mode CHECK (mode IN ('preview','execute')),"
        " CONSTRAINT ck_safe_action_status CHECK (status IN ('pending','pending_approval','approved','rejected','running','succeeded','failed','timed_out')),"
        " CONSTRAINT uq_safe_action_idempotency UNIQUE(tenant_id, action_key, idempotency_key)"
        ")",
        "CREATE INDEX ix_safe_action_executions_tenant ON safe_action_executions(tenant_id, created_at DESC)",
        "CREATE INDEX ix_safe_action_executions_ticket ON safe_action_executions(ticket_id)",
        "CREATE TABLE safe_action_approvals ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " execution_id uuid NOT NULL REFERENCES safe_action_executions(id) ON DELETE CASCADE,"
        " requested_by uuid NOT NULL REFERENCES users(id),"
        " decided_by uuid REFERENCES users(id),"
        " decision varchar(20) NOT NULL DEFAULT 'pending',"
        " reason text,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " decided_at timestamptz,"
        " CONSTRAINT ck_safe_action_approval_decision CHECK (decision IN ('pending','approved','rejected'))"
        ")",
        "CREATE INDEX ix_safe_action_approvals_execution ON safe_action_approvals(execution_id)",
        "CREATE TABLE safe_action_results ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " execution_id uuid NOT NULL REFERENCES safe_action_executions(id) ON DELETE CASCADE UNIQUE,"
        " result_summary text NOT NULL,"
        " result_data jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " evidence jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " sandbox boolean NOT NULL DEFAULT false,"
        " rollback_available boolean NOT NULL DEFAULT false,"
        " rolled_back boolean NOT NULL DEFAULT false,"
        " created_at timestamptz NOT NULL DEFAULT now()"
        ")",
        "CREATE INDEX ix_safe_action_results_execution ON safe_action_results(execution_id)",
    ]
    for statement in statements:
        op.execute(statement)

    from sqlalchemy import text
    bind = op.get_bind()
    for d in DEFINITIONS:
        bind.execute(text(
            "INSERT INTO safe_action_definitions(action_key,display_name,description,category,risk_level,"
            "parameter_schema,requires_confirmation,requires_customer_consent,connector,timeout_seconds,"
            "supports_dry_run,supports_rollback) VALUES (:action_key,:display_name,:description,:category,:risk_level,"
            ":parameter_schema,:requires_confirmation,:requires_customer_consent,:connector,:timeout_seconds,"
            ":supports_dry_run,:supports_rollback) ON CONFLICT (action_key) DO NOTHING"
        ), {**d, "parameter_schema": json.dumps(d["parameter_schema"])})

    op.execute("INSERT INTO permissions(code) VALUES ('safe_action:execute') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE p.code='safe_action:execute' AND r.name IN ('system_admin','team_lead','support_agent','reviewer') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in ("safe_action_results", "safe_action_approvals", "safe_action_executions", "safe_action_definitions"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
