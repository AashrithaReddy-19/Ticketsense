"""V2 Phase 6: deterministic counterfactual decision explanations

Revision ID: 0031
Revises: 0030
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE counterfactual_explanations ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, "
        "ticket_decision_id uuid NOT NULL REFERENCES ticket_decisions(id) ON DELETE CASCADE, "
        "explanation_version varchar(40) NOT NULL, decision_outcome varchar(30) NOT NULL, "
        "input_passed_gates jsonb NOT NULL DEFAULT '[]'::jsonb, input_failed_gates jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "input_factors jsonb NOT NULL DEFAULT '{}'::jsonb, "
        "blocking_gates jsonb NOT NULL DEFAULT '[]'::jsonb, immutable_reasons jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "evidence_gaps jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "narrative_internal text NOT NULL, narrative_customer text NOT NULL, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_counterfactual_decision_version UNIQUE(ticket_decision_id, explanation_version))",
        "CREATE INDEX ix_counterfactual_explanations_tenant_id ON counterfactual_explanations(tenant_id)",
        "CREATE INDEX ix_counterfactual_explanations_ticket_id ON counterfactual_explanations(ticket_id)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS counterfactual_explanations")
