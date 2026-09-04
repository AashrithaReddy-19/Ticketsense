"""three public experiences and safe enterprise workflow foundation

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "ALTER TABLE users ADD COLUMN public_role varchar(20)",
        "UPDATE users SET public_role=CASE WHEN role IN ('customer','end_user') THEN 'customer' WHEN role IN ('support_agent','department_engineer') THEN 'engineer' ELSE 'admin' END",
        "ALTER TABLE users ALTER COLUMN public_role SET NOT NULL",
        "ALTER TABLE users ALTER COLUMN public_role SET DEFAULT 'customer'",
        "ALTER TABLE users ADD CONSTRAINT ck_users_public_role CHECK (public_role IN ('customer','engineer','admin'))",
        "ALTER TABLE tickets DROP CONSTRAINT ck_tickets_status",
        "ALTER TABLE tickets ALTER COLUMN status TYPE varchar(30)",
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_status CHECK (status IN ('submitted','needs_clarification','ai_processing','awaiting_assignment','assigned','in_progress','awaiting_customer','escalated','resolved_by_ai','resolved_by_engineer','reopened','closed','ai_processing_failed','processing','classified','routed','pending_review','changes_requested','approved','resolved'))",
        "ALTER TABLE tickets ADD COLUMN category varchar(120)",
        "ALTER TABLE tickets ADD COLUMN required_specialization varchar(120)",
        "ALTER TABLE tickets ADD COLUMN resolution_type varchar(30)",
        "ALTER TABLE tickets ADD COLUMN auto_resolution_eligible boolean NOT NULL DEFAULT false",
        "ALTER TABLE tickets ADD COLUMN auto_resolution_reason_code varchar(80)",
        "ALTER TABLE tickets ADD COLUMN reopened_count integer NOT NULL DEFAULT 0",
        "ALTER TABLE tickets ADD COLUMN sla_due_at timestamptz",
        "ALTER TABLE tickets ADD COLUMN parent_incident_id uuid REFERENCES incidents(id) ON DELETE SET NULL",
        "ALTER TABLE tickets ADD COLUMN last_auto_resolution_fingerprint varchar(64)",
        "ALTER TABLE tickets ADD COLUMN first_response_at timestamptz",
        "ALTER TABLE tickets ADD COLUMN complexity_weight numeric NOT NULL DEFAULT 1.0",
        "CREATE INDEX ix_tickets_category ON tickets(category)",
        "CREATE INDEX ix_tickets_required_specialization ON tickets(required_specialization)",
        "CREATE INDEX ix_tickets_resolution_type ON tickets(resolution_type)",
        "CREATE INDEX ix_tickets_sla_due_at ON tickets(sla_due_at)",
        "CREATE INDEX ix_tickets_parent_incident_id ON tickets(parent_incident_id)",
        "CREATE TABLE engineer_profiles (user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, availability_status varchar(20) NOT NULL DEFAULT 'available', max_weighted_capacity double precision NOT NULL DEFAULT 10.0, availability_schedule jsonb NOT NULL DEFAULT '{}'::jsonb, performance_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_engineer_profiles_availability CHECK (availability_status IN ('available','busy','away','offline')))",
        "CREATE INDEX ix_engineer_profiles_tenant_id ON engineer_profiles(tenant_id)",
        "CREATE TABLE engineer_skills (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE, specialization varchar(120) NOT NULL, skill_level varchar(20) NOT NULL DEFAULT 'intermediate', is_primary boolean NOT NULL DEFAULT false, is_active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_engineer_skill_scope UNIQUE(user_id,department_id,specialization), CONSTRAINT ck_engineer_skills_level CHECK (skill_level IN ('none','basic','intermediate','advanced','expert')))",
        "CREATE INDEX ix_engineer_skills_tenant_id ON engineer_skills(tenant_id)",
        "CREATE INDEX ix_engineer_skills_user_id ON engineer_skills(user_id)",
        "CREATE INDEX ix_engineer_skills_department_id ON engineer_skills(department_id)",
        "INSERT INTO engineer_profiles(user_id,tenant_id,availability_status,max_weighted_capacity) SELECT id,tenant_id,CASE WHEN is_available THEN 'available' ELSE 'offline' END,max_active_workload::double precision FROM users WHERE tenant_id IS NOT NULL AND role IN ('support_agent','department_engineer') ON CONFLICT DO NOTHING",
        "INSERT INTO engineer_skills(tenant_id,user_id,department_id,specialization,skill_level,is_primary) SELECT u.tenant_id,s.user_id,s.department_id,s.name,'intermediate',row_number() OVER(PARTITION BY s.user_id ORDER BY s.created_at,s.id)=1 FROM engineer_specializations s JOIN users u ON u.id=s.user_id WHERE u.tenant_id IS NOT NULL ON CONFLICT DO NOTHING",
        "CREATE TABLE department_resolution_policies (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, department_id uuid REFERENCES departments(id) ON DELETE CASCADE, category varchar(120), risk_class varchar(40), version integer NOT NULL, allow_auto_resolution boolean NOT NULL DEFAULT false, auto_resolve_threshold double precision NOT NULL DEFAULT 0.85, minimum_citation_coverage double precision NOT NULL DEFAULT 0.8, minimum_retrieval_score double precision NOT NULL DEFAULT 0.65, minimum_classification_confidence double precision NOT NULL DEFAULT 0.75, minimum_classification_margin double precision NOT NULL DEFAULT 0.15, auto_resolution_allowlist jsonb NOT NULL DEFAULT '[]'::jsonb, sensitive_category_denylist jsonb NOT NULL DEFAULT '[]'::jsonb, is_active boolean NOT NULL DEFAULT true, updated_by uuid NOT NULL REFERENCES users(id), reason text, created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_resolution_policy_threshold CHECK(auto_resolve_threshold BETWEEN 0 AND 1), CONSTRAINT ck_resolution_policy_citations CHECK(minimum_citation_coverage BETWEEN 0 AND 1), CONSTRAINT ck_resolution_policy_retrieval CHECK(minimum_retrieval_score BETWEEN 0 AND 1), CONSTRAINT ck_resolution_policy_classification CHECK(minimum_classification_confidence BETWEEN 0 AND 1), CONSTRAINT ck_resolution_policy_margin CHECK(minimum_classification_margin BETWEEN 0 AND 1))",
        "CREATE INDEX ix_resolution_policies_scope ON department_resolution_policies(tenant_id,department_id,category,risk_class,is_active,version DESC)",
        "CREATE TABLE ticket_decisions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, pipeline_execution_id uuid REFERENCES pipeline_executions(id) ON DELETE SET NULL, policy_id uuid REFERENCES department_resolution_policies(id) ON DELETE SET NULL, decision varchar(30) NOT NULL, reason_code varchar(80) NOT NULL, explanation text NOT NULL, overall_confidence double precision, applicable_threshold double precision, passed_gates jsonb NOT NULL DEFAULT '[]'::jsonb, failed_gates jsonb NOT NULL DEFAULT '[]'::jsonb, factors jsonb NOT NULL DEFAULT '{}'::jsonb, response_fingerprint varchar(64), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_ticket_decision_execution UNIQUE(ticket_id,pipeline_execution_id), CONSTRAINT ck_ticket_decisions_decision CHECK(decision IN ('auto_resolve','assign_engineer','admin_intervention','processing_failed')))",
        "CREATE INDEX ix_ticket_decisions_tenant_id ON ticket_decisions(tenant_id)",
        "CREATE INDEX ix_ticket_decisions_ticket_id ON ticket_decisions(ticket_id)",
        "CREATE TABLE confidence_components (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), ticket_decision_id uuid NOT NULL REFERENCES ticket_decisions(id) ON DELETE CASCADE, component varchar(80) NOT NULL, score double precision, passed boolean NOT NULL, threshold double precision, detail varchar(500), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_confidence_component_decision UNIQUE(ticket_decision_id,component))",
        "CREATE INDEX ix_confidence_components_decision ON confidence_components(ticket_decision_id)",
        "CREATE TABLE assignment_decisions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, engineer_id uuid REFERENCES users(id) ON DELETE SET NULL, actor_id uuid REFERENCES users(id) ON DELETE SET NULL, decision_type varchar(30) NOT NULL, score double precision, factor_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb, explanation text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_assignment_decisions_ticket ON assignment_decisions(tenant_id,ticket_id,created_at DESC)",
        "CREATE INDEX ix_assignment_decisions_engineer ON assignment_decisions(engineer_id)",
        "CREATE TABLE ticket_messages (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, author_id uuid NOT NULL REFERENCES users(id), visibility varchar(10) NOT NULL, body text NOT NULL, original_language varchar(12) NOT NULL DEFAULT 'en', translated_body text, translated_language varchar(12), machine_translated boolean NOT NULL DEFAULT false, attachment_ids jsonb NOT NULL DEFAULT '[]'::jsonb, idempotency_key varchar(120), edited_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_ticket_messages_visibility CHECK(visibility IN ('public','internal')), CONSTRAINT uq_ticket_messages_idempotency UNIQUE(tenant_id,idempotency_key))",
        "CREATE INDEX ix_ticket_messages_scope ON ticket_messages(tenant_id,ticket_id,created_at)",
        "CREATE TABLE ticket_message_reads (message_id uuid NOT NULL REFERENCES ticket_messages(id) ON DELETE CASCADE, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(message_id,user_id))",
        "CREATE TABLE resolution_confirmations (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, user_id uuid NOT NULL REFERENCES users(id), outcome varchar(20) NOT NULL, reason text, response_fingerprint varchar(64), idempotency_key varchar(120), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_resolution_confirmations_outcome CHECK(outcome IN ('solved','needs_help')), CONSTRAINT uq_resolution_confirmations_idempotency UNIQUE(tenant_id,idempotency_key))",
        "CREATE INDEX ix_resolution_confirmations_ticket ON resolution_confirmations(tenant_id,ticket_id,created_at DESC)",
        "CREATE TABLE diagnostic_plans (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, created_by uuid NOT NULL REFERENCES users(id), status varchar(30) NOT NULL DEFAULT 'active', summary text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_diagnostic_plans_ticket ON diagnostic_plans(tenant_id,ticket_id)",
        "CREATE TABLE diagnostic_steps (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), plan_id uuid NOT NULL REFERENCES diagnostic_plans(id) ON DELETE CASCADE, sequence_number integer NOT NULL, title varchar(255) NOT NULL, instruction text NOT NULL, status varchar(30) NOT NULL DEFAULT 'pending', safety_warning text, evidence_required boolean NOT NULL DEFAULT false, result_note text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_diagnostic_step_sequence UNIQUE(plan_id,sequence_number), CONSTRAINT ck_diagnostic_steps_status CHECK(status IN ('pending','passed','failed','not_applicable','requires_escalation')))",
        "CREATE INDEX ix_diagnostic_steps_plan ON diagnostic_steps(plan_id)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = (
        "policy:manage", "message:internal", "diagnostic:manage", "assignment:override",
        "incident:manage", "knowledge:approve", "analytics:all", "safe_action:execute",
    )
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p WHERE (r.name='support_agent' AND p.code IN ('message:internal','diagnostic:manage')) OR (r.name='reviewer' AND p.code IN ('message:internal','diagnostic:manage')) OR (r.name='team_lead' AND p.code IN ('message:internal','diagnostic:manage','assignment:override','incident:manage','analytics:all')) OR (r.name='knowledge_manager' AND p.code IN ('knowledge:approve')) OR (r.name='system_admin' AND p.code IN ('policy:manage','message:internal','diagnostic:manage','assignment:override','incident:manage','knowledge:approve','analytics:all','safe_action:execute')) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    for table in (
        "diagnostic_steps", "diagnostic_plans", "resolution_confirmations",
        "ticket_message_reads", "ticket_messages", "assignment_decisions",
        "confidence_components", "ticket_decisions", "department_resolution_policies",
        "engineer_skills", "engineer_profiles",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for index in (
        "ix_tickets_parent_incident_id", "ix_tickets_sla_due_at", "ix_tickets_resolution_type",
        "ix_tickets_required_specialization", "ix_tickets_category",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index}")
    for column in (
        "complexity_weight", "first_response_at", "last_auto_resolution_fingerprint",
        "parent_incident_id", "sla_due_at", "reopened_count", "auto_resolution_reason_code",
        "auto_resolution_eligible", "resolution_type", "required_specialization", "category",
    ):
        op.execute(f"ALTER TABLE tickets DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT ck_tickets_status")
    op.execute("UPDATE tickets SET status=CASE WHEN status IN ('needs_clarification','ai_processing','ai_processing_failed') THEN 'processing' WHEN status='awaiting_assignment' THEN 'routed' WHEN status='awaiting_customer' THEN 'in_progress' WHEN status='resolved_by_ai' OR status='resolved_by_engineer' THEN 'resolved' ELSE status END")
    op.execute("ALTER TABLE tickets ALTER COLUMN status TYPE varchar(20)")
    op.execute("ALTER TABLE tickets ADD CONSTRAINT ck_tickets_status CHECK (status IN ('submitted','processing','classified','routed','assigned','in_progress','pending_review','changes_requested','approved','resolved','escalated','closed','reopened'))")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_public_role")
    op.execute("ALTER TABLE users DROP COLUMN public_role")
