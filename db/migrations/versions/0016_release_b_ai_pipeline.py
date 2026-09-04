"""persist Release B pipeline traces, technical entities and claim validation

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ddl = """
    CREATE TABLE pipeline_executions (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES organizations(id), ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
      pipeline_version varchar(40) NOT NULL, trigger_type varchar(40) NOT NULL, status varchar(30) NOT NULL,
      started_at timestamptz NOT NULL, completed_at timestamptz, total_duration_ms integer, failure_stage varchar(80),
      fallback_used boolean NOT NULL DEFAULT false, correlation_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_pipeline_executions_tenant_id ON pipeline_executions(tenant_id);
    CREATE INDEX ix_pipeline_executions_ticket_id ON pipeline_executions(ticket_id);
    CREATE INDEX ix_pipeline_executions_status ON pipeline_executions(status);
    CREATE INDEX ix_pipeline_executions_correlation_id ON pipeline_executions(correlation_id);
    CREATE TABLE pipeline_stages (
      id uuid PRIMARY KEY, execution_id uuid NOT NULL REFERENCES pipeline_executions(id) ON DELETE CASCADE,
      stage_name varchar(80) NOT NULL, sequence_number integer NOT NULL, status varchar(30) NOT NULL,
      input_summary varchar(300), output_summary varchar(500), provider_name varchar(100), provider_version varchar(120), confidence double precision,
      started_at timestamptz NOT NULL, completed_at timestamptz NOT NULL, duration_ms integer NOT NULL,
      error_category varchar(80), safe_error_summary varchar(300), fallback_used boolean NOT NULL DEFAULT false,
      metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_pipeline_stage_sequence UNIQUE(execution_id,sequence_number));
    CREATE INDEX ix_pipeline_stages_execution_id ON pipeline_stages(execution_id);
    CREATE TABLE technical_entities (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES organizations(id), ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
      entity_type varchar(60) NOT NULL, raw_value varchar(500) NOT NULL, normalized_value varchar(500) NOT NULL,
      source varchar(40) NOT NULL, extraction_method varchar(80) NOT NULL, confidence double precision NOT NULL,
      start_offset integer, end_offset integer, validation_status varchar(30) NOT NULL DEFAULT 'extracted', corrected_from_id uuid REFERENCES technical_entities(id),
      created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_technical_entities_tenant_id ON technical_entities(tenant_id);
    CREATE INDEX ix_technical_entities_ticket_id ON technical_entities(ticket_id);
    CREATE UNIQUE INDEX uq_technical_entities_original ON technical_entities(ticket_id,entity_type,normalized_value,source) WHERE corrected_from_id IS NULL;
    CREATE TABLE claim_validations (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES organizations(id), ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
      execution_id uuid NOT NULL REFERENCES pipeline_executions(id) ON DELETE CASCADE, claim_text text NOT NULL,
      citation_id varchar(40), evidence_excerpt text, validation_status varchar(40) NOT NULL, risk_level varchar(20) NOT NULL,
      reason varchar(500) NOT NULL, validator_version varchar(80) NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_claim_validations_tenant_id ON claim_validations(tenant_id);
    CREATE INDEX ix_claim_validations_ticket_id ON claim_validations(ticket_id);
    CREATE INDEX ix_claim_validations_execution_id ON claim_validations(execution_id);
    """
    for statement in ddl.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in ("claim_validations", "technical_entities", "pipeline_stages", "pipeline_executions"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
