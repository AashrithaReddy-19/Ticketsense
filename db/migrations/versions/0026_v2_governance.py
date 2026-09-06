"""V2 Phase 1 feature governance, registries and observability

Revision ID: 0026
Revises: 0025
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE feature_flags (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), key varchar(100) UNIQUE NOT NULL, description text NOT NULL, owner varchar(120) NOT NULL, global_default boolean NOT NULL DEFAULT false, kill_switch boolean NOT NULL DEFAULT false, prerequisites jsonb NOT NULL DEFAULT '[]'::jsonb, starts_at timestamptz, ends_at timestamptz, created_by uuid REFERENCES users(id) ON DELETE SET NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_feature_flags_key ON feature_flags(key)",
        "CREATE TABLE feature_flag_overrides (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), flag_id uuid NOT NULL REFERENCES feature_flags(id) ON DELETE CASCADE, tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, scope_type varchar(20) NOT NULL, scope_value varchar(160) NOT NULL, enabled boolean NOT NULL, rollout_percentage integer NOT NULL DEFAULT 100, starts_at timestamptz, ends_at timestamptz, reason text NOT NULL, updated_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_feature_override_scope UNIQUE(flag_id,tenant_id,scope_type,scope_value), CONSTRAINT ck_feature_override_scope_type CHECK(scope_type IN ('tenant','department','user','role','capability')), CONSTRAINT ck_feature_override_rollout CHECK(rollout_percentage BETWEEN 0 AND 100))",
        "CREATE INDEX ix_feature_flag_overrides_flag_id ON feature_flag_overrides(flag_id)",
        "CREATE INDEX ix_feature_flag_overrides_tenant_id ON feature_flag_overrides(tenant_id)",
        "CREATE TABLE feature_flag_audits (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid REFERENCES organizations(id) ON DELETE CASCADE, flag_id uuid NOT NULL REFERENCES feature_flags(id) ON DELETE CASCADE, override_id uuid REFERENCES feature_flag_overrides(id) ON DELETE SET NULL, actor_id uuid REFERENCES users(id) ON DELETE SET NULL, action varchar(50) NOT NULL, before jsonb NOT NULL DEFAULT '{}'::jsonb, after jsonb NOT NULL DEFAULT '{}'::jsonb, reason text, created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_feature_flag_audits_scope ON feature_flag_audits(tenant_id,flag_id,created_at DESC)",
        "CREATE TABLE provider_models (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, provider_type varchar(60) NOT NULL, model_identifier varchar(160) NOT NULL, immutable_version varchar(120) NOT NULL, task_type varchar(80) NOT NULL, deployment_environment varchar(40) NOT NULL DEFAULT 'development', config_reference varchar(200), enabled boolean NOT NULL DEFAULT false, cost_metadata jsonb NOT NULL DEFAULT '{}'::jsonb, latency_limit_ms integer, data_residency_policy varchar(100) NOT NULL DEFAULT 'tenant_default', approved_scopes jsonb NOT NULL DEFAULT '{}'::jsonb, evaluation_status varchar(30) NOT NULL DEFAULT 'not_evaluated', lifecycle_role varchar(20) NOT NULL DEFAULT 'challenger', rollback_target_id uuid REFERENCES provider_models(id) ON DELETE SET NULL, created_by uuid NOT NULL REFERENCES users(id), approved_by uuid REFERENCES users(id), approved_at timestamptz, deployed_by uuid REFERENCES users(id), deployed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_provider_model_version UNIQUE(tenant_id,provider_type,model_identifier,immutable_version,task_type,deployment_environment), CONSTRAINT ck_provider_models_role CHECK(lifecycle_role IN ('champion','challenger','shadow','retired')), CONSTRAINT ck_provider_models_evaluation CHECK(evaluation_status IN ('not_evaluated','running','approved','rejected','insufficient_data')))",
        "CREATE INDEX ix_provider_models_scope ON provider_models(tenant_id,task_type,deployment_environment,lifecycle_role)",
        "CREATE UNIQUE INDEX uq_provider_model_champion ON provider_models(tenant_id,task_type,deployment_environment) WHERE lifecycle_role='champion' AND enabled=true",
        "CREATE TABLE model_deployments (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, task_type varchar(80) NOT NULL, from_model_id uuid REFERENCES provider_models(id) ON DELETE SET NULL, to_model_id uuid REFERENCES provider_models(id) ON DELETE SET NULL, action varchar(20) NOT NULL, actor_id uuid NOT NULL REFERENCES users(id), reason text NOT NULL, evaluation_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_model_deployments_action CHECK(action IN ('promote','rollback','disable')))",
        "CREATE INDEX ix_model_deployments_scope ON model_deployments(tenant_id,task_type,created_at DESC)",
        "CREATE TABLE prompt_versions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, task_type varchar(80) NOT NULL, name varchar(120) NOT NULL, version varchar(60) NOT NULL, template text NOT NULL, content_hash varchar(64) NOT NULL, structured_output_schema jsonb NOT NULL DEFAULT '{}'::jsonb, is_active boolean NOT NULL DEFAULT false, created_by uuid NOT NULL REFERENCES users(id), approved_by uuid REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_prompt_version UNIQUE(tenant_id,task_type,name,version))",
        "CREATE INDEX ix_prompt_versions_scope ON prompt_versions(tenant_id,task_type,is_active)",
        "CREATE TABLE ai_usage_events (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, ticket_id uuid REFERENCES tickets(id) ON DELETE SET NULL, model_id uuid REFERENCES provider_models(id) ON DELETE SET NULL, task_type varchar(80) NOT NULL, provider varchar(80) NOT NULL, model_version varchar(160) NOT NULL, latency_ms integer NOT NULL, input_tokens integer, output_tokens integer, estimated_cost_usd numeric(14,8), cache_hit boolean NOT NULL DEFAULT false, success boolean NOT NULL, error_category varchar(80), correlation_id uuid, metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_ai_usage_events_scope ON ai_usage_events(tenant_id,task_type,created_at DESC)",
        "CREATE INDEX ix_ai_usage_events_ticket_id ON ai_usage_events(ticket_id)",
        "CREATE INDEX ix_ai_usage_events_model_id ON ai_usage_events(model_id)",
        "CREATE INDEX ix_ai_usage_events_correlation_id ON ai_usage_events(correlation_id)",
        "CREATE TABLE capability_bundles (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, key varchar(100) NOT NULL, name varchar(160) NOT NULL, description text NOT NULL, conflicts_with jsonb NOT NULL DEFAULT '[]'::jsonb, is_active boolean NOT NULL DEFAULT true, created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_capability_bundle_key UNIQUE(tenant_id,key))",
        "CREATE INDEX ix_capability_bundles_tenant_id ON capability_bundles(tenant_id)",
        "CREATE TABLE capability_bundle_permissions (bundle_id uuid NOT NULL REFERENCES capability_bundles(id) ON DELETE CASCADE, permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE, PRIMARY KEY(bundle_id,permission_id))",
        "CREATE TABLE user_capability_bundles (user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, bundle_id uuid NOT NULL REFERENCES capability_bundles(id) ON DELETE CASCADE, tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, department_id uuid REFERENCES departments(id) ON DELETE CASCADE, assigned_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,bundle_id,tenant_id))",
        "CREATE INDEX ix_user_capability_bundles_scope ON user_capability_bundles(tenant_id,department_id,user_id)",
    ]
    for statement in statements:
        op.execute(statement)

    for key, description, owner in (
        ("evaluation_lab", "Reproducible model and RAG evaluation laboratory", "AI Governance"),
        ("resolution_passport", "Role-safe immutable resolution passports", "Support Platform"),
        ("counterfactual_explanations", "Stored-gate counterfactual decision explanations", "AI Governance"),
        ("graphrag", "Tenant-safe dependency graph retrieval", "Knowledge Platform"),
        ("shadow_mode", "Private non-mutating candidate inference", "MLOps"),
        ("challenger_models", "Champion and challenger lifecycle management", "MLOps"),
        ("red_team_lab", "Isolated adversarial AI safety evaluation", "Security"),
        ("multimodal_analysis", "Versioned screenshot and log diagnostic adapters", "AI Platform"),
        ("change_correlation", "Change-aware incident hypotheses", "Operations"),
        ("real_time_events", "Authorized server-sent ticket events", "Platform"),
        ("external_connectors", "Production-shaped allowlisted connectors", "Integrations"),
        ("adaptive_thresholds", "Risk-aware threshold simulation and policy proposals", "AI Governance"),
        ("knowledge_conflict_detection", "Contradictory knowledge detection and resolution blocking", "Knowledge Platform"),
        ("process_mining", "Event-history process variants and bottlenecks", "Operations"),
    ):
        safe_description = description.replace("'", "''")
        op.execute(f"INSERT INTO feature_flags(key,description,owner,global_default) VALUES ('{key}','{safe_description}','{owner}',false) ON CONFLICT(key) DO NOTHING")

    permission_codes = ("feature:read", "feature:manage", "feature:manage_global", "model:read", "model:manage", "prompt:manage", "observability:read", "capability_bundle:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p WHERE (r.name='system_admin' AND p.code IN ('feature:read','feature:manage','feature:manage_global','model:read','model:manage','prompt:manage','observability:read','capability_bundle:manage')) OR (r.name='team_lead' AND p.code IN ('feature:read','model:read','observability:read')) OR (r.name='auditor' AND p.code IN ('feature:read','model:read','observability:read')) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    for table in ("user_capability_bundles", "capability_bundle_permissions", "capability_bundles", "ai_usage_events", "prompt_versions", "model_deployments", "provider_models", "feature_flag_audits", "feature_flag_overrides", "feature_flags"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('feature:read','feature:manage','feature:manage_global','model:read','model:manage','prompt:manage','observability:read','capability_bundle:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('feature:read','feature:manage','feature:manage_global','model:read','model:manage','prompt:manage','observability:read','capability_bundle:manage')")
