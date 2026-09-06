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
    "support_agent": frozenset({"ticket:read_department", "ticket:update", "ticket:internal_ai", "ticket:note_internal", "ticket:escalate", "knowledge:read", "message:internal", "diagnostic:manage", "safe_action:execute", "passport:read"}),
    "reviewer": frozenset({"ticket:read_department", "ticket:internal_ai", "review:manage", "ticket:assign", "ticket:escalate", "knowledge:read", "message:internal", "diagnostic:manage", "safe_action:execute", "passport:read"}),
    "knowledge_manager": frozenset({"knowledge:read", "knowledge:manage", "knowledge:publish", "knowledge:approve"}),
    "team_lead": frozenset({"ticket:read_department", "ticket:update", "ticket:internal_ai", "ticket:assign", "ticket:escalate", "review:manage", "analytics:department", "knowledge:read", "message:internal", "diagnostic:manage", "assignment:override", "incident:manage", "analytics:all", "playbook:manage", "prevention:manage", "dataset:read", "evaluation:read", "threshold:read", "passport:read", "passport:export"}),
    "system_admin": frozenset({"ticket:read_all", "ticket:update", "ticket:internal_ai", "ticket:assign", "ticket:escalate", "review:manage", "user:manage", "engineer:manage", "department:manage", "tenant:configure", "integration:manage", "system:monitor", "audit:read", "knowledge:manage", "knowledge:approve", "policy:manage", "message:internal", "diagnostic:manage", "assignment:override", "incident:manage", "analytics:all", "safe_action:execute", "playbook:manage", "prevention:manage", "feature:read", "feature:manage", "feature:manage_global", "model:read", "model:manage", "prompt:manage", "observability:read", "capability_bundle:manage", "dataset:read", "dataset:manage", "evaluation:read", "evaluation:manage", "threshold:read", "threshold:simulate", "passport:read", "passport:export", "passport:manage"}),
    "auditor": frozenset({"audit:read", "compliance:export", "feature:read", "model:read", "observability:read", "dataset:read", "evaluation:read", "threshold:read", "passport:read", "passport:export"}),
    # Legacy specialist role retained until its capabilities move to scoped permissions.
    "ai_admin": frozenset({"system:monitor", "ai:monitor"}),
}


def canonical_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)


def has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(canonical_role(role), frozenset())


def is_customer(role: str) -> bool:
    return canonical_role(role) == "customer"


def public_role(role: str) -> str:
    """Map compatibility roles to one of the three product experiences."""
    canonical = canonical_role(role)
    if canonical == "customer":
        return "customer"
    if canonical == "support_agent":
        return "engineer"
    return "admin"
