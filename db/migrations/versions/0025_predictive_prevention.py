"""Section 20: evidence-backed predictive-prevention recommendations

Revision ID: 0025
Revises: 0024

Three tables rather than the four sometimes suggested for this feature:
recommendation_reviews (reviewer/decision/reason/timestamp) is folded directly
into prevention_recommendations as columns, since it is a strict 1:1 with the
recommendation (a recommendation has exactly one current review state) and a
separate table would only duplicate that with no additional cardinality.
recommendation_actions remains separate as the append-only action history
(every transition + its specific outcome, e.g. which article/incident it was
linked to) — genuinely one-to-many, unlike a "current review state".
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE prevention_recommendations ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,"
        " department_id uuid REFERENCES departments(id) ON DELETE SET NULL,"
        " category varchar(120),"
        " recommendation_type varchar(60) NOT NULL,"
        " title varchar(255) NOT NULL,"
        " description text NOT NULL,"
        " window_days integer NOT NULL,"
        " supporting_ticket_count integer NOT NULL DEFAULT 0,"
        " evidence_strength varchar(20) NOT NULL,"
        " expected_benefit text NOT NULL,"
        " status varchar(30) NOT NULL DEFAULT 'new',"
        " decision_reason text,"
        " linked_incident_id uuid REFERENCES incidents(id) ON DELETE SET NULL,"
        " linked_knowledge_article_id uuid REFERENCES knowledge_articles(id) ON DELETE SET NULL,"
        " generated_at timestamptz NOT NULL DEFAULT now(),"
        " decided_by uuid REFERENCES users(id),"
        " decided_at timestamptz,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT ck_prevention_rec_type CHECK (recommendation_type IN ("
        "  'create_knowledge_article','update_knowledge_article','investigate_version',"
        "  'publish_customer_announcement','conduct_training','add_monitoring',"
        "  'review_capacity_allocation','investigate_infrastructure'"
        " )),"
        " CONSTRAINT ck_prevention_rec_strength CHECK (evidence_strength IN ('low','medium','high')),"
        " CONSTRAINT ck_prevention_rec_status CHECK (status IN ("
        "  'new','under_investigation','accepted','rejected','dismissed','converted'"
        " ))"
        ")",
        "CREATE INDEX ix_prevention_rec_scope ON prevention_recommendations(tenant_id, department_id, category, status)",
        "CREATE INDEX ix_prevention_rec_type ON prevention_recommendations(tenant_id, recommendation_type)",
        "CREATE TABLE recommendation_evidence ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " recommendation_id uuid NOT NULL REFERENCES prevention_recommendations(id) ON DELETE CASCADE,"
        " evidence_type varchar(60) NOT NULL,"
        " reference_id uuid,"
        " detail jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " created_at timestamptz NOT NULL DEFAULT now()"
        ")",
        "CREATE INDEX ix_recommendation_evidence_recommendation ON recommendation_evidence(recommendation_id)",
        "CREATE TABLE recommendation_actions ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " recommendation_id uuid NOT NULL REFERENCES prevention_recommendations(id) ON DELETE CASCADE,"
        " actor_id uuid NOT NULL REFERENCES users(id),"
        " action_type varchar(30) NOT NULL,"
        " reason text,"
        " result_reference_id uuid,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT ck_recommendation_action_type CHECK (action_type IN ("
        "  'accept','reject','investigate','dismiss','convert_to_knowledge','link_incident'"
        " ))"
        ")",
        "CREATE INDEX ix_recommendation_actions_recommendation ON recommendation_actions(recommendation_id, created_at DESC)",
    ]
    for statement in statements:
        op.execute(statement)

    op.execute("INSERT INTO permissions(code) VALUES ('prevention:manage') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE p.code='prevention:manage' AND r.name IN ('system_admin','team_lead') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in ("recommendation_actions", "recommendation_evidence", "prevention_recommendations"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
