"""V2 Phase 8: shadow-mode sampling and champion/challenger comparison

Revision ID: 0033
Revises: 0032
"""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE shadow_runs ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, task_type varchar(20) NOT NULL, "
        "champion_model_id uuid REFERENCES provider_models(id) ON DELETE SET NULL, "
        "challenger_model_id uuid REFERENCES provider_models(id) ON DELETE SET NULL, "
        "redacted_input text NOT NULL, input_hash varchar(64) NOT NULL, actual_label varchar(160), "
        "champion_output varchar(160), champion_confidence numeric(6,4), champion_latency_ms integer, "
        "challenger_output varchar(160), challenger_confidence numeric(6,4), challenger_latency_ms integer, "
        "agreement boolean, created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT ck_shadow_runs_task CHECK(task_type IN ('department','priority','sentiment')))",
        "CREATE INDEX ix_shadow_runs_tenant_task ON shadow_runs(tenant_id, task_type, created_at DESC)",
        "CREATE INDEX ix_shadow_runs_ticket_id ON shadow_runs(ticket_id)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shadow_runs")
