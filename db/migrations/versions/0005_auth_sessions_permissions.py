"""normalized permissions and revocable refresh sessions

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ROLES = ("customer", "support_agent", "reviewer", "knowledge_manager", "team_lead", "system_admin", "auditor", "ai_admin")
CATALOGUE = {
 "customer": ("ticket:create","ticket:read_own","ticket:comment_public","ticket:reopen","ticket:close","feedback:create"),
 "support_agent": ("ticket:read_department","ticket:transition","ticket:comment_public","ticket:note_internal","ticket:escalate","ai:view_summary","ai:view_evidence","ai:view_confidence","knowledge:read"),
 "reviewer": ("ticket:read_department","ticket:review","ai:view_summary","ai:view_evidence","ai:view_confidence","knowledge:read"),
 "knowledge_manager": ("knowledge:read","knowledge:create","knowledge:review","knowledge:publish"),
 "team_lead": ("ticket:read_department","ticket:assign","ticket:transition","ticket:escalate","ai:view_summary","ai:view_evidence","ai:view_confidence","analytics:department","knowledge:read"),
 "system_admin": ("user:manage","settings:manage","integration:manage","system:monitor","audit:read"),
 "auditor": ("audit:read","audit:export"),
 "ai_admin": ("system:monitor","ai:monitor"),
}

def upgrade() -> None:
    op.execute("CREATE TABLE roles (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(40) UNIQUE NOT NULL, description text, created_at timestamptz NOT NULL DEFAULT now())")
    op.execute("CREATE TABLE permissions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code varchar(100) UNIQUE NOT NULL, description text, created_at timestamptz NOT NULL DEFAULT now())")
    op.execute("CREATE TABLE role_permissions (role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE, permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE, PRIMARY KEY(role_id,permission_id))")
    op.execute("CREATE TABLE user_roles (user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE, tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, department_id uuid REFERENCES departments(id), created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,role_id,tenant_id))")
    op.execute("CREATE INDEX ix_user_roles_scope ON user_roles(tenant_id,department_id,user_id)")
    op.execute("CREATE TABLE auth_sessions (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash varchar(64) UNIQUE NOT NULL, csrf_hash varchar(64) NOT NULL, ip_address varchar(64), user_agent varchar(512), expires_at timestamptz NOT NULL, revoked_at timestamptz, replaced_by_id uuid, reuse_detected_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), last_used_at timestamptz)")
    op.execute("CREATE INDEX ix_auth_sessions_user_active ON auth_sessions(user_id,revoked_at,expires_at)")
    for role in ROLES:
        op.execute(f"INSERT INTO roles(name) VALUES ('{role}')")
    permissions = sorted({p for values in CATALOGUE.values() for p in values})
    for permission in permissions:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{permission}')")
    for role, values in CATALOGUE.items():
        for permission in values:
            op.execute(f"INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r,permissions p WHERE r.name='{role}' AND p.code='{permission}'")
    op.execute("""INSERT INTO user_roles(user_id,role_id,tenant_id,department_id)
      SELECT u.id,r.id,u.tenant_id,u.department_id FROM users u JOIN roles r ON r.name=CASE
       WHEN u.role IN ('end_user') THEN 'customer' WHEN u.role='department_engineer' THEN 'support_agent'
       WHEN u.role='manager' THEN 'team_lead' WHEN u.role IN ('enterprise_admin','admin') THEN 'system_admin'
       WHEN u.role='security_admin' THEN 'auditor' ELSE u.role END WHERE u.tenant_id IS NOT NULL
      ON CONFLICT DO NOTHING""")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_sessions,user_roles,role_permissions,permissions,roles CASCADE")
