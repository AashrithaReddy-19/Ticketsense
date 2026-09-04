"""assignment capacity, confidence policies, richer audits and pipeline metrics

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN is_available boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE users ADD COLUMN max_active_workload integer NOT NULL DEFAULT 10")
    op.execute("ALTER TABLE users ADD COLUMN last_assigned_at timestamptz")
    op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_workload_positive CHECK(max_active_workload > 0)")
    op.execute("ALTER TABLE tickets ADD COLUMN assignment_reason text")
    op.execute("ALTER TABLE tickets ADD COLUMN assigned_at timestamptz")
    op.execute("ALTER TABLE response_drafts ADD COLUMN creator_role varchar(30)")
    op.execute("ALTER TABLE response_drafts ADD COLUMN confidence_score double precision")
    op.execute("ALTER TABLE response_drafts ADD COLUMN is_final boolean NOT NULL DEFAULT false")
    op.execute("UPDATE response_drafts d SET creator_role=COALESCE(u.role,d.author_type) FROM users u WHERE u.id=d.created_by_user_id")
    op.execute("UPDATE response_drafts d SET is_final=true FROM tickets t WHERE t.final_response_draft_id=d.id")
    op.execute("ALTER TABLE ticket_events ADD COLUMN old_assignee_id uuid REFERENCES users(id)")
    op.execute("ALTER TABLE ticket_events ADD COLUMN new_assignee_id uuid REFERENCES users(id)")
    op.execute("ALTER TABLE ticket_events ADD COLUMN correlation_id uuid")
    op.execute("ALTER TABLE ticket_events ADD COLUMN metadata_json jsonb NOT NULL DEFAULT '{}'")
    op.execute("CREATE INDEX ix_ticket_events_created ON ticket_events(tenant_id,created_at DESC)")
    op.execute("CREATE INDEX ix_users_assignment_eligibility ON users(tenant_id,department_id,is_active,is_available,last_assigned_at) WHERE role IN ('support_agent','department_engineer')")
    op.execute("CREATE TABLE department_confidence_policies(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES organizations(id),department_id uuid NOT NULL REFERENCES departments(id),low_threshold double precision NOT NULL,high_threshold double precision NOT NULL,version integer NOT NULL,effective_at timestamptz NOT NULL,updated_by uuid NOT NULL REFERENCES users(id),reason text,created_at timestamptz NOT NULL DEFAULT now(),CONSTRAINT uq_department_confidence_version UNIQUE(tenant_id,department_id,version),CONSTRAINT ck_confidence_low_range CHECK(low_threshold>=0 AND low_threshold<=1),CONSTRAINT ck_confidence_high_range CHECK(high_threshold>=0 AND high_threshold<=1),CONSTRAINT ck_confidence_threshold_order CHECK(low_threshold<=high_threshold))")
    op.execute("CREATE INDEX ix_department_confidence_current ON department_confidence_policies(tenant_id,department_id,version DESC)")
    op.execute("CREATE TABLE pipeline_metrics(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES organizations(id),ticket_id uuid REFERENCES tickets(id) ON DELETE CASCADE,trace_id uuid NOT NULL,stage varchar(60) NOT NULL,started_at timestamptz NOT NULL,ended_at timestamptz NOT NULL,duration_ms integer NOT NULL,success boolean NOT NULL DEFAULT true,provider_version varchar(120),error_category varchar(80),metadata_json jsonb NOT NULL DEFAULT '{}',created_at timestamptz NOT NULL DEFAULT now())")
    op.execute("CREATE INDEX ix_pipeline_metrics_analysis ON pipeline_metrics(tenant_id,stage,created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pipeline_metrics")
    op.execute("DROP TABLE IF EXISTS department_confidence_policies")
    op.execute("DROP INDEX IF EXISTS ix_users_assignment_eligibility")
    op.execute("DROP INDEX IF EXISTS ix_ticket_events_created")
    for column in ("metadata_json","correlation_id","new_assignee_id","old_assignee_id"): op.drop_column("ticket_events",column)
    for column in ("is_final","confidence_score","creator_role"): op.drop_column("response_drafts",column)
    for column in ("assigned_at","assignment_reason"): op.drop_column("tickets",column)
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_workload_positive")
    for column in ("last_assigned_at","max_active_workload","is_available"): op.drop_column("users",column)
