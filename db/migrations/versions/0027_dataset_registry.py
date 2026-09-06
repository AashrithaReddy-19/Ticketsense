"""V2 Phase 2: dataset registry, leakage-safe splits, ingestion batches

Revision ID: 0027
Revises: 0026
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE datasets (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, key varchar(100) NOT NULL, name varchar(200) NOT NULL, kind varchar(30) NOT NULL, description text NOT NULL, license_notes text NOT NULL DEFAULT '', created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_dataset_key UNIQUE(tenant_id,key), CONSTRAINT ck_datasets_kind CHECK(kind IN ('ticket_labels','retrieval_judgments')))",
        "CREATE INDEX ix_datasets_tenant_id ON datasets(tenant_id)",
        "CREATE TABLE dataset_versions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE, version_number integer NOT NULL, content_hash varchar(64) NOT NULL, row_count integer NOT NULL DEFAULT 0, label_distribution jsonb NOT NULL DEFAULT '{}'::jsonb, missing_data_stats jsonb NOT NULL DEFAULT '{}'::jsonb, duplicate_rate numeric(6,4) NOT NULL DEFAULT 0, corruption_rate numeric(6,4) NOT NULL DEFAULT 0, near_duplicate_cross_split_count integer NOT NULL DEFAULT 0, near_duplicate_check_skipped boolean NOT NULL DEFAULT false, split_ratio jsonb NOT NULL DEFAULT '{}'::jsonb, split_seed varchar(80) NOT NULL, status varchar(20) NOT NULL DEFAULT 'processing', provenance jsonb NOT NULL DEFAULT '{}'::jsonb, created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_dataset_version_number UNIQUE(dataset_id,version_number), CONSTRAINT ck_dataset_versions_status CHECK(status IN ('processing','ready','reverted','failed')))",
        "CREATE INDEX ix_dataset_versions_dataset_id ON dataset_versions(dataset_id)",
        "CREATE TABLE dataset_import_batches (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_version_id uuid NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE, source_filename varchar(300) NOT NULL, source_format varchar(10) NOT NULL, raw_row_count integer NOT NULL, accepted_row_count integer NOT NULL, rejected_row_count integer NOT NULL, rejection_reasons jsonb NOT NULL DEFAULT '{}'::jsonb, reverted_at timestamptz, reverted_by uuid REFERENCES users(id), created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_dataset_import_batches_format CHECK(source_format IN ('csv','json','jsonl')))",
        "CREATE INDEX ix_dataset_import_batches_version_id ON dataset_import_batches(dataset_version_id)",
        "CREATE TABLE dataset_rows (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_version_id uuid NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE, import_batch_id uuid NOT NULL REFERENCES dataset_import_batches(id) ON DELETE CASCADE, tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, department_id uuid REFERENCES departments(id) ON DELETE SET NULL, row_index integer NOT NULL, group_key varchar(200) NOT NULL, redacted_text text NOT NULL, content_hash varchar(64) NOT NULL, near_duplicate_of uuid REFERENCES dataset_rows(id) ON DELETE SET NULL, language_code varchar(8) NOT NULL DEFAULT 'unknown', pii_categories jsonb NOT NULL DEFAULT '[]'::jsonb, corruption_flags jsonb NOT NULL DEFAULT '[]'::jsonb, label_department varchar(120), label_priority varchar(20), label_sentiment varchar(20), query_text text, relevant_document_ref varchar(200), relevance_grade integer, split varchar(10) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT ck_dataset_rows_split CHECK(split IN ('train','validation','test')))",
        "CREATE INDEX ix_dataset_rows_version_id ON dataset_rows(dataset_version_id)",
        "CREATE INDEX ix_dataset_rows_batch_id ON dataset_rows(import_batch_id)",
        "CREATE INDEX ix_dataset_rows_tenant_id ON dataset_rows(tenant_id)",
        "CREATE INDEX ix_dataset_rows_department_id ON dataset_rows(department_id)",
        "CREATE INDEX ix_dataset_rows_group_key ON dataset_rows(dataset_version_id,group_key)",
        "CREATE INDEX ix_dataset_rows_content_hash ON dataset_rows(content_hash)",
        "CREATE INDEX ix_dataset_rows_split ON dataset_rows(dataset_version_id,split)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("dataset:read", "dataset:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('dataset:read','dataset:manage')) "
        "OR (r.name='team_lead' AND p.code = 'dataset:read') "
        "OR (r.name='auditor' AND p.code = 'dataset:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in ("dataset_rows", "dataset_import_batches", "dataset_versions", "datasets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('dataset:read','dataset:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('dataset:read','dataset:manage')")
