"""synchronized response workflow and draft versions

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_status")
    op.execute("UPDATE tickets SET status='submitted' WHERE status='open'")
    op.execute("UPDATE tickets SET status='pending_review' WHERE status='in_review'")
    op.execute("ALTER TABLE tickets ADD CONSTRAINT ck_tickets_status CHECK (status IN ('submitted','processing','classified','routed','assigned','in_progress','pending_review','changes_requested','approved','resolved','escalated','closed','reopened'))")
    for statement in (
        "ALTER TABLE tickets ADD COLUMN final_response text",
        "ALTER TABLE tickets ADD COLUMN latest_draft_id uuid",
        "ALTER TABLE tickets ADD COLUMN final_response_draft_id uuid",
        "ALTER TABLE tickets ADD COLUMN final_responder_id uuid REFERENCES users(id)",
        "ALTER TABLE tickets ADD COLUMN final_approver_id uuid REFERENCES users(id)",
        "ALTER TABLE tickets ADD COLUMN approved_at timestamptz",
        "ALTER TABLE tickets ADD COLUMN resolved_at timestamptz",
        "ALTER TABLE tickets ADD COLUMN public_status_message text",
    ): op.execute(statement)
    op.execute("UPDATE tickets SET final_response=ai_draft_reply,resolved_at=updated_at,approved_at=updated_at,public_status_message='A reviewed resolution has been provided.' WHERE status='resolved' AND ai_draft_reply IS NOT NULL")
    op.execute("CREATE TABLE response_drafts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES organizations(id),ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,version_number integer NOT NULL,content text NOT NULL,author_type varchar(20) NOT NULL,created_by_user_id uuid REFERENCES users(id),based_on_draft_id uuid REFERENCES response_drafts(id),citations jsonb NOT NULL DEFAULT '[]',status varchar(30) NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),CONSTRAINT uq_response_drafts_ticket_version UNIQUE(ticket_id,version_number),CONSTRAINT ck_response_drafts_author_type CHECK(author_type IN ('ai','engineer','reviewer')),CONSTRAINT ck_response_drafts_status CHECK(status IN ('generated','engineer_edited','submitted_for_review','changes_requested','reviewer_modified','approved','rejected','superseded')))")
    op.execute("CREATE INDEX ix_response_drafts_ticket ON response_drafts(tenant_id,ticket_id,version_number DESC)")
    op.execute("INSERT INTO response_drafts(tenant_id,ticket_id,version_number,content,author_type,citations,status,created_at,updated_at) SELECT tenant_id,id,1,ai_draft_reply,'ai','[]','approved',updated_at,updated_at FROM tickets WHERE ai_draft_reply IS NOT NULL")
    op.execute("UPDATE tickets t SET latest_draft_id=d.id,final_response_draft_id=CASE WHEN t.status='resolved' THEN d.id END FROM response_drafts d WHERE d.ticket_id=t.id AND d.version_number=1")
    op.execute("CREATE TABLE ticket_events(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES organizations(id),ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,event_type varchar(50) NOT NULL,old_status varchar(30),new_status varchar(30),actor_id uuid REFERENCES users(id),actor_role varchar(30),comment text,draft_version integer,visibility varchar(10) NOT NULL DEFAULT 'internal',created_at timestamptz NOT NULL DEFAULT now(),CONSTRAINT ck_ticket_events_visibility CHECK(visibility IN ('internal','customer','both')))")
    op.execute("CREATE INDEX ix_ticket_events_scope ON ticket_events(tenant_id,ticket_id,created_at)")
    op.execute("CREATE TABLE engineer_departments(user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(user_id,department_id))")
    op.execute("INSERT INTO engineer_departments(user_id,department_id) SELECT id,department_id FROM users WHERE department_id IS NOT NULL AND role IN ('support_agent','department_engineer') ON CONFLICT DO NOTHING")
    op.execute("CREATE TABLE engineer_specializations(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE,name varchar(120) NOT NULL,created_at timestamptz NOT NULL DEFAULT now())")
    op.execute("CREATE INDEX ix_engineer_specializations_scope ON engineer_specializations(department_id,user_id)")
    op.execute("CREATE INDEX ix_tickets_workflow ON tickets(tenant_id,department_id,status,assignee_id) WHERE deleted_at IS NULL")
    op.execute("INSERT INTO permissions(code) VALUES ('ticket:read_all'),('review:manage'),('engineer:manage'),('department:manage') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p WHERE (r.name='team_lead' AND p.code IN ('ticket:review','review:manage')) OR (r.name='reviewer' AND p.code IN ('ticket:assign','ticket:escalate','review:manage')) OR (r.name='system_admin' AND p.code IN ('ticket:read_all','ticket:read_department','ticket:assign','ticket:transition','ticket:escalate','ticket:review','review:manage','engineer:manage','department:manage','ai:view_summary','ai:view_evidence','ai:view_confidence','knowledge:read')) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tickets_workflow")
    op.execute("DROP TABLE IF EXISTS engineer_specializations")
    op.execute("DROP TABLE IF EXISTS engineer_departments")
    op.execute("DROP TABLE IF EXISTS ticket_events")
    op.execute("DROP TABLE IF EXISTS response_drafts")
    for column in ("public_status_message","resolved_at","approved_at","final_approver_id","final_responder_id","final_response_draft_id","latest_draft_id","final_response"):
        op.drop_column("tickets", column)
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_status")
    op.execute("UPDATE tickets SET status='open' WHERE status IN ('submitted','processing','classified','routed','assigned','in_progress','changes_requested','reopened')")
    op.execute("UPDATE tickets SET status='in_review' WHERE status IN ('pending_review','approved')")
    op.execute("ALTER TABLE tickets ADD CONSTRAINT ck_tickets_status CHECK(status IN ('open','in_review','resolved','escalated','closed'))")
