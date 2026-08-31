"""ticket queues, assignment, reviewer workflow and scoped data repair

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision="0007"; down_revision="0006"; branch_labels=None; depends_on=None

def upgrade()->None:
    op.execute("ALTER TABLE tickets ADD COLUMN assignee_id uuid REFERENCES users(id)")
    op.execute("ALTER TABLE tickets ADD COLUMN analysis_status varchar(30) NOT NULL DEFAULT 'complete'")
    op.execute("ALTER TABLE tickets ADD COLUMN review_required boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE tickets ADD COLUMN review_reason text")
    op.execute("ALTER TABLE tickets ADD COLUMN escalation_level varchar(30)")
    op.execute("ALTER TABLE tickets ADD COLUMN routing_state varchar(30) NOT NULL DEFAULT 'routed'")
    op.execute("ALTER TABLE tickets ADD COLUMN sensitivity varchar(30) NOT NULL DEFAULT 'internal'")
    op.execute("ALTER TABLE tickets ADD COLUMN deleted_at timestamptz")
    op.execute("CREATE INDEX ix_tickets_queue ON tickets(tenant_id,department_id,assignee_id,status) WHERE deleted_at IS NULL")
    op.execute("CREATE TABLE human_reviews(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES organizations(id),ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,reviewer_id uuid NOT NULL REFERENCES users(id),decision varchar(20) NOT NULL,reason text NOT NULL,original_ai_draft text,final_response text,confidence_snapshot numeric,risk_snapshot jsonb NOT NULL DEFAULT '{}',evidence_snapshot jsonb NOT NULL DEFAULT '[]',created_at timestamptz NOT NULL DEFAULT now())")
    op.execute("CREATE INDEX ix_human_reviews_ticket ON human_reviews(tenant_id,ticket_id,created_at)")
    # Existing VPN/network tickets were unrouted because customers have no department.
    # Repair only NULL department rows whose analysis/category or text maps confidently.
    op.execute("""WITH mapped AS (SELECT t.id,d.id department_id FROM tickets t JOIN departments d ON d.tenant_id=t.tenant_id AND d.name='Networking' WHERE t.department_id IS NULL AND (lower(t.subject||' '||t.description) ~ 'vpn|wifi|wi-fi|network|dns|firewall')) UPDATE tickets t SET department_id=m.department_id,routing_state='routed',review_required=(t.status='in_review'),review_reason=CASE WHEN t.status='in_review' THEN 'AI result requires human validation' END FROM mapped m WHERE t.id=m.id""")
    op.execute("UPDATE tickets SET routing_state='manual_triage',review_required=(status='in_review'),review_reason=CASE WHEN status='in_review' THEN 'AI result requires human validation' END WHERE department_id IS NULL")
    op.execute("""INSERT INTO audit_logs(tenant_id,user_id,action,resource_type,resource_id,metadata_json) SELECT t.tenant_id,NULL,'ticket.scope_repaired','ticket',t.id::text,jsonb_build_object('department_id',t.department_id,'routing_state',t.routing_state) FROM tickets t WHERE NOT EXISTS(SELECT 1 FROM audit_logs a WHERE a.action='ticket.scope_repaired' AND a.resource_id=t.id::text)""")
    op.execute("INSERT INTO permissions(code) VALUES ('ticket:triage_general'),('ticket:read_audit_metadata') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r JOIN permissions p ON p.code='ticket:triage_general' WHERE r.name IN ('support_agent','team_lead') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r JOIN permissions p ON p.code='ticket:read_audit_metadata' WHERE r.name='auditor' ON CONFLICT DO NOTHING")

def downgrade()->None:
    op.execute("DROP TABLE IF EXISTS human_reviews")
    op.execute("DROP INDEX IF EXISTS ix_tickets_queue")
    for col in ('deleted_at','sensitivity','routing_state','escalation_level','review_reason','review_required','analysis_status','assignee_id'): op.drop_column('tickets',col)
