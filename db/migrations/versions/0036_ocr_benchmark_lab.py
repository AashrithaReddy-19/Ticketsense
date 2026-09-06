"""V2 Phase 11: OCR/multimodal diagnostic benchmark lab

Revision ID: 0036
Revises: 0035
"""
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE ocr_benchmark_datasets ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "key varchar(100) NOT NULL, name varchar(200) NOT NULL, description text NOT NULL DEFAULT '', "
        "created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_ocr_benchmark_dataset_key UNIQUE(tenant_id, key))",
        "CREATE INDEX ix_ocr_benchmark_datasets_tenant_id ON ocr_benchmark_datasets(tenant_id)",

        "CREATE TABLE ocr_benchmark_cases ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "dataset_id uuid NOT NULL REFERENCES ocr_benchmark_datasets(id) ON DELETE CASCADE, "
        "tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "storage_key varchar(300) NOT NULL, image_sha256 varchar(64) NOT NULL, ground_truth_text text NOT NULL, "
        "source_label varchar(20) NOT NULL DEFAULT 'synthetic', tags jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_ocr_benchmark_cases_dataset_id ON ocr_benchmark_cases(dataset_id)",
        "CREATE INDEX ix_ocr_benchmark_cases_tenant_id ON ocr_benchmark_cases(tenant_id)",

        "CREATE TABLE ocr_benchmark_runs ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "dataset_id uuid NOT NULL REFERENCES ocr_benchmark_datasets(id) ON DELETE CASCADE, "
        "engine varchar(30) NOT NULL, status varchar(20) NOT NULL, unavailable_reason text, "
        "row_count_considered integer NOT NULL DEFAULT 0, "
        "mean_character_error_rate numeric(6,4), mean_word_error_rate numeric(6,4), mean_latency_ms numeric(10,2), "
        "environment_info jsonb NOT NULL DEFAULT '{}'::jsonb, "
        "started_at timestamptz NOT NULL, completed_at timestamptz, "
        "created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT ck_ocr_benchmark_runs_engine CHECK(engine IN ('tesseract','easyocr','paddleocr')), "
        "CONSTRAINT ck_ocr_benchmark_runs_status CHECK(status IN ('completed','engine_unavailable','insufficient_data','failed')))",
        "CREATE INDEX ix_ocr_benchmark_runs_tenant_id ON ocr_benchmark_runs(tenant_id, dataset_id)",

        "CREATE TABLE ocr_benchmark_results ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "run_id uuid NOT NULL REFERENCES ocr_benchmark_runs(id) ON DELETE CASCADE, "
        "case_id uuid NOT NULL REFERENCES ocr_benchmark_cases(id) ON DELETE CASCADE, "
        "extracted_text text NOT NULL DEFAULT '', character_error_rate numeric(6,4) NOT NULL, "
        "word_error_rate numeric(6,4) NOT NULL, latency_ms numeric(10,2) NOT NULL)",
        "CREATE INDEX ix_ocr_benchmark_results_run_id ON ocr_benchmark_results(run_id)",
        "CREATE INDEX ix_ocr_benchmark_results_case_id ON ocr_benchmark_results(case_id)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("ocr_benchmark:read", "ocr_benchmark:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('ocr_benchmark:read','ocr_benchmark:manage')) "
        "OR (r.name='team_lead' AND p.code = 'ocr_benchmark:read') "
        "OR (r.name='auditor' AND p.code = 'ocr_benchmark:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ocr_benchmark_results")
    op.execute("DROP TABLE IF EXISTS ocr_benchmark_runs")
    op.execute("DROP TABLE IF EXISTS ocr_benchmark_cases")
    op.execute("DROP TABLE IF EXISTS ocr_benchmark_datasets")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('ocr_benchmark:read','ocr_benchmark:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('ocr_benchmark:read','ocr_benchmark:manage')")
