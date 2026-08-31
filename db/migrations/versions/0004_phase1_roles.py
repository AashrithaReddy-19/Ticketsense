"""add canonical governance roles

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_role")
    op.execute("""ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN (
      'customer','support_agent','reviewer','knowledge_manager','team_lead',
      'system_admin','auditor','ai_admin','manager','enterprise_admin',
      'security_admin','end_user','department_engineer','admin'))""")


def downgrade() -> None:
    op.execute("UPDATE users SET role='manager' WHERE role IN ('reviewer','team_lead')")
    op.execute("UPDATE users SET role='enterprise_admin' WHERE role='system_admin'")
    op.execute("UPDATE users SET role='security_admin' WHERE role='auditor'")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_role")
    op.execute("""ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN (
      'customer','support_agent','manager','enterprise_admin','ai_admin',
      'knowledge_manager','security_admin','end_user','department_engineer','admin'))""")
