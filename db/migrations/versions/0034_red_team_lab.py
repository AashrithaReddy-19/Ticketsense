"""V2 Phase 9: adversarial AI safety / red-team laboratory

Revision ID: 0034
Revises: 0033
"""
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE red_team_suites ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), suite_key varchar(80) NOT NULL, name varchar(200) NOT NULL, "
        "version integer NOT NULL, description text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_red_team_suite_version UNIQUE(suite_key, version))",
        "CREATE TABLE red_team_cases ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), suite_id uuid NOT NULL REFERENCES red_team_suites(id) ON DELETE CASCADE, "
        "case_key varchar(100) NOT NULL, category varchar(40) NOT NULL, severity varchar(20) NOT NULL, "
        "title varchar(200) NOT NULL, description text NOT NULL, expected_result varchar(40) NOT NULL, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_red_team_case_key UNIQUE(suite_id, case_key), "
        "CONSTRAINT ck_red_team_cases_category CHECK(category IN ('prompt_injection','malicious_knowledge_document','system_prompt_disclosure','fabricated_citations','cross_tenant_retrieval','encoded_secrets','unsafe_instructions','contradictory_knowledge','tool_parameter_injection','ssrf_path_traversal','role_escalation')), "
        "CONSTRAINT ck_red_team_cases_severity CHECK(severity IN ('low','medium','high','critical')))",
        "CREATE INDEX ix_red_team_cases_suite_id ON red_team_cases(suite_id)",
        "CREATE TABLE red_team_runs ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "suite_id uuid NOT NULL REFERENCES red_team_suites(id) ON DELETE CASCADE, suite_version integer NOT NULL, "
        "status varchar(20) NOT NULL, started_at timestamptz NOT NULL, completed_at timestamptz, "
        "triggered_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT ck_red_team_runs_status CHECK(status IN ('completed','failed')))",
        "CREATE INDEX ix_red_team_runs_tenant_id ON red_team_runs(tenant_id, created_at DESC)",
        "CREATE TABLE red_team_results ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES red_team_runs(id) ON DELETE CASCADE, "
        "case_id uuid NOT NULL REFERENCES red_team_cases(id) ON DELETE CASCADE, observed_result varchar(40) NOT NULL, "
        "passed boolean NOT NULL, applicable boolean NOT NULL DEFAULT true, gate_responsible varchar(80), "
        "detail text NOT NULL, evidence jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_red_team_results_run_id ON red_team_results(run_id)",
        "CREATE INDEX ix_red_team_results_case_id ON red_team_results(case_id)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("red_team:read", "red_team:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('red_team:read','red_team:manage')) "
        "OR (r.name='auditor' AND p.code = 'red_team:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in ("red_team_results", "red_team_runs", "red_team_cases", "red_team_suites"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('red_team:read','red_team:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('red_team:read','red_team:manage')")
