from app.services.ticket_intelligence import redact
from app.core.rbac import canonical_role, has_permission


def test_redacts_external_pii():
    clean, kinds = redact("Contact jane@example.com and password: SuperSecret123")
    assert "jane@example.com" not in clean
    assert "SuperSecret123" not in clean
    assert set(kinds) == {"email", "secret"}


def test_non_sensitive_text_is_unchanged():
    source = "VPN authentication fails after MFA reset"
    clean, kinds = redact(source)
    assert clean == source
    assert kinds == []


def test_customer_cannot_read_internal_ai_or_audits():
    assert not has_permission("customer", "ticket:internal_ai")
    assert not has_permission("customer", "audit:read")


def test_auditor_is_read_only():
    assert has_permission("auditor", "audit:read")
    assert not has_permission("auditor", "ticket:update")
    assert not has_permission("auditor", "knowledge:publish")


def test_legacy_roles_map_to_canonical_roles():
    assert canonical_role("manager") == "team_lead"
    assert canonical_role("enterprise_admin") == "system_admin"
    assert canonical_role("security_admin") == "auditor"
