"""V2 Phase 3: reproducible evaluation runs, metrics and artifacts

Revision ID: 0028
Revises: 0027
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE evaluation_runs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, dataset_version_id uuid NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE, target varchar(20) NOT NULL, model_artifact_path varchar(300) NOT NULL, model_artifact_hash varchar(64), git_commit varchar(40), environment_info jsonb NOT NULL DEFAULT '{}'::jsonb, config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb, split_used varchar(10) NOT NULL DEFAULT 'test', status varchar(20) NOT NULL, row_count_considered integer NOT NULL DEFAULT 0, row_count_excluded integer NOT NULL DEFAULT 0, exclusion_reasons jsonb NOT NULL DEFAULT '{}'::jsonb, started_at timestamptz NOT NULL, completed_at timestamptz, notes text, created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_evaluation_runs_target CHECK(target IN ('department','priority','sentiment')), CONSTRAINT ck_evaluation_runs_status CHECK(status IN ('completed','failed','insufficient_data')))",
        "CREATE INDEX ix_evaluation_runs_scope ON evaluation_runs(tenant_id,target,created_at DESC)",
        "CREATE INDEX ix_evaluation_runs_dataset_version_id ON evaluation_runs(dataset_version_id)",
        "CREATE TABLE evaluation_examples (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE, dataset_row_id uuid NOT NULL REFERENCES dataset_rows(id) ON DELETE CASCADE, true_label varchar(120) NOT NULL, predicted_label varchar(120) NOT NULL, correct boolean NOT NULL, top_3_hit boolean, predicted_confidence numeric(6,4))",
        "CREATE INDEX ix_evaluation_examples_run_id ON evaluation_examples(run_id)",
        "CREATE INDEX ix_evaluation_examples_run_correct ON evaluation_examples(run_id,correct)",
        "CREATE TABLE evaluation_metrics (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE, scope varchar(20) NOT NULL, class_label varchar(120), metric_name varchar(80) NOT NULL, metric_value numeric(10,6) NOT NULL, support integer, CONSTRAINT ck_evaluation_metrics_scope CHECK(scope IN ('overall','per_class')))",
        "CREATE INDEX ix_evaluation_metrics_run_id ON evaluation_metrics(run_id)",
        "CREATE TABLE evaluation_artifacts (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE, artifact_type varchar(40) NOT NULL, content jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_evaluation_artifacts_type CHECK(artifact_type IN ('confusion_matrix')))",
        "CREATE INDEX ix_evaluation_artifacts_run_id ON evaluation_artifacts(run_id)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("evaluation:read", "evaluation:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('evaluation:read','evaluation:manage')) "
        "OR (r.name='team_lead' AND p.code = 'evaluation:read') "
        "OR (r.name='auditor' AND p.code = 'evaluation:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in ("evaluation_artifacts", "evaluation_metrics", "evaluation_examples", "evaluation_runs"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('evaluation:read','evaluation:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('evaluation:read','evaluation:manage')")
