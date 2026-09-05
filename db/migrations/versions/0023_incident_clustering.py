"""Section 14: duplicate-to-incident clustering

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "ALTER TABLE incidents ADD COLUMN department_id uuid REFERENCES departments(id) ON DELETE SET NULL",
        "ALTER TABLE incidents ADD COLUMN category varchar(120)",
        "ALTER TABLE incidents ADD COLUMN confirmed_by uuid REFERENCES users(id)",
        "ALTER TABLE incidents ADD COLUMN confirmed_at timestamptz",
        "ALTER TABLE incidents ADD COLUMN resolved_at timestamptz",
        "ALTER TABLE incidents ADD COLUMN detection_reason text",
        "CREATE INDEX ix_incidents_department_scope ON incidents(tenant_id, department_id, category, status)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    for column in ("detection_reason", "resolved_at", "confirmed_at", "confirmed_by", "category", "department_id"):
        op.execute(f"ALTER TABLE incidents DROP COLUMN IF EXISTS {column}")
