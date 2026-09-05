"""reconcile database role_permissions with the enforcement-side static RBAC table

The frontend's nav/module visibility and every DB-driven permission check
(``_permissions()``, ``user_has_permission()``) read only from role_permissions.
backend/app/core/rbac.py's PERMISSIONS dict is the intended source of truth for
what each canonical role should be able to do, but past migrations only ever
granted a subset of it — most visibly, system_admin and knowledge_manager were
both missing knowledge:manage, so the Admin "Knowledge" nav item and module
card (both gated on that exact permission) silently never appeared for anyone.

This migration is intentionally idempotent and additive: it inserts any
(role, permission) pair from the current static table that is not already
present in the database, and never removes an existing grant (a superset
already present in the database — e.g. legacy ticket:update/ticket:transition
naming — is left untouched).

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


# Mirrors backend/app/core/rbac.py:PERMISSIONS at the time of writing. Kept as a
# literal snapshot (not an import) because a migration's behavior must stay fixed
# even if the application file changes again later.
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "customer": ("ticket:create", "ticket:read_own", "ticket:comment_public", "ticket:reopen", "ticket:close", "feedback:create"),
    "support_agent": ("ticket:read_department", "ticket:update", "ticket:internal_ai", "ticket:note_internal", "ticket:escalate", "knowledge:read", "message:internal", "diagnostic:manage"),
    "reviewer": ("ticket:read_department", "ticket:internal_ai", "review:manage", "ticket:assign", "ticket:escalate", "knowledge:read", "message:internal", "diagnostic:manage"),
    "knowledge_manager": ("knowledge:read", "knowledge:manage", "knowledge:publish", "knowledge:approve"),
    "team_lead": ("ticket:read_department", "ticket:update", "ticket:internal_ai", "ticket:assign", "ticket:escalate", "review:manage", "analytics:department", "knowledge:read", "message:internal", "diagnostic:manage", "assignment:override", "incident:manage", "analytics:all"),
    "system_admin": ("ticket:read_all", "ticket:update", "ticket:internal_ai", "ticket:assign", "ticket:escalate", "review:manage", "user:manage", "engineer:manage", "department:manage", "tenant:configure", "integration:manage", "system:monitor", "audit:read", "knowledge:manage", "knowledge:approve", "policy:manage", "message:internal", "diagnostic:manage", "assignment:override", "incident:manage", "analytics:all", "safe_action:execute"),
    "auditor": ("audit:read", "compliance:export"),
    "ai_admin": ("system:monitor", "ai:monitor"),
}


def upgrade() -> None:
    all_codes = sorted({code for codes in ROLE_PERMISSIONS.values() for code in codes})
    for code in all_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    for role, codes in ROLE_PERMISSIONS.items():
        codes_list = ",".join(f"'{code}'" for code in codes)
        op.execute(
            f"INSERT INTO role_permissions(role_id, permission_id) "
            f"SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            f"WHERE r.name = '{role}' AND p.code IN ({codes_list}) "
            f"ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    # Deliberately a no-op: this migration only ever adds grants that the static
    # RBAC table already declared the role should have, so there is nothing
    # tenant-specific or unintended to revert. Removing them would risk taking
    # away a grant a downstream migration or the admin UI came to depend on.
    pass
