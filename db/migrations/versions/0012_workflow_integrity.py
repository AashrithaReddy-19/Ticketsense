"""enforce final-response and draft-reference workflow integrity

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A legacy resolved row without a response cannot truthfully remain resolved.
    op.execute(
        "UPDATE tickets SET status='pending_review',review_required=true,"
        "public_status_message='The proposed resolution is being reviewed.' "
        "WHERE status='resolved' AND final_response IS NULL"
    )
    # Backfilled AI drafts are working material unless they became a final response.
    op.execute(
        "UPDATE response_drafts d SET status='generated' FROM tickets t "
        "WHERE d.ticket_id=t.id AND t.final_response_draft_id IS DISTINCT FROM d.id "
        "AND d.status='approved'"
    )
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT fk_tickets_latest_draft "
        "FOREIGN KEY(latest_draft_id) REFERENCES response_drafts(id) DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT fk_tickets_final_response_draft "
        "FOREIGN KEY(final_response_draft_id) REFERENCES response_drafts(id) DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_resolved_has_response "
        "CHECK(status NOT IN ('approved','resolved') OR "
        "(final_response IS NOT NULL AND final_response_draft_id IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX ix_tickets_pending_review ON tickets(tenant_id,department_id,updated_at DESC) "
        "WHERE status='pending_review' AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tickets_pending_review")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_resolved_has_response")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS fk_tickets_final_response_draft")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS fk_tickets_latest_draft")

