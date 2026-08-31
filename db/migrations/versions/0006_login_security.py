"""persistent login lockout

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN failed_login_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN locked_until timestamptz")
    op.execute("CREATE INDEX ix_users_locked_until ON users(locked_until) WHERE locked_until IS NOT NULL")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_locked_until")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
