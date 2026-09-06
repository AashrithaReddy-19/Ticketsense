"""V2 Phase 12: production-shaped external connector (Slack webhook)

Revision ID: 0037
Revises: 0036
"""
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "ALTER TABLE integrations ADD COLUMN config_reference varchar(200)",
        "ALTER TABLE integrations ADD COLUMN status varchar(20) NOT NULL DEFAULT 'not_configured'",
        "ALTER TABLE integrations ADD COLUMN last_verified_at timestamptz",
        "ALTER TABLE integrations ADD COLUMN last_verified_by uuid REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE integrations ADD COLUMN last_error text",
        "ALTER TABLE integrations ADD CONSTRAINT ck_integrations_status CHECK(status IN ('not_configured','unverified','verified','failed'))",
        "ALTER TABLE integrations ADD CONSTRAINT ck_integrations_config_reference CHECK("
        "config_reference IS NULL OR config_reference LIKE 'env:%' OR config_reference LIKE 'secret-manager:%' "
        "OR config_reference LIKE 'none:%' OR config_reference LIKE 'file:%')",
    ]
    for statement in statements:
        op.execute(statement)

    op.execute("INSERT INTO permissions(code) VALUES ('integration:read') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE p.code='integration:read' AND r.name IN ('system_admin','team_lead','auditor') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE integrations DROP CONSTRAINT IF EXISTS ck_integrations_config_reference")
    op.execute("ALTER TABLE integrations DROP CONSTRAINT IF EXISTS ck_integrations_status")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS last_error")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS last_verified_by")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS last_verified_at")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS config_reference")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code='integration:read')")
    op.execute("DELETE FROM permissions WHERE code='integration:read'")
