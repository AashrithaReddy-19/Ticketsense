"""Central role and permission policy for backend-enforced authorization.

The aliases keep existing installations compatible while the seven canonical
roles are introduced through migrations and seed data.
"""

ROLE_ALIASES = {
    "end_user": "customer",
    "department_engineer": "support_agent",
    "manager": "team_lead",
    "enterprise_admin": "system_admin",
    "admin": "system_admin",
    "security_admin": "auditor",
}

PERMISSIONS: dict[str, frozenset[str]] = {
    "customer": frozenset({"ticket:create", "ticket:read_own", "ticket:comment_public", "ticket:reopen", "ticket:close", "feedback:create"}),
    "support_agent": frozenset({"ticket:read_department", "ticket:update", "ticket:internal_ai", "ticket:note_internal", "ticket:escalate", "knowledge:read"}),
    "reviewer": frozenset({"ticket:read_department", "ticket:internal_ai", "review:manage", "knowledge:read"}),
    "knowledge_manager": frozenset({"knowledge:read", "knowledge:manage", "knowledge:publish"}),
    "team_lead": frozenset({"ticket:read_department", "ticket:update", "ticket:internal_ai", "ticket:assign", "ticket:escalate", "analytics:department", "knowledge:read"}),
    "system_admin": frozenset({"user:manage", "tenant:configure", "integration:manage", "system:monitor", "audit:read"}),
    "auditor": frozenset({"audit:read", "compliance:export"}),
    # Legacy specialist role retained until its capabilities move to scoped permissions.
    "ai_admin": frozenset({"system:monitor", "ai:monitor"}),
}


def canonical_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)


def has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(canonical_role(role), frozenset())


def is_customer(role: str) -> bool:
    return canonical_role(role) == "customer"
