"""Section 14: duplicate-ticket clustering into Admin-confirmable incidents."""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.database import async_session_maker
from app.main import app
from app.models.department import Department
from app.models.platform import Incident, Organization
from app.models.ticket import Ticket
from app.models.user import User
from app.services.incidents import detect_incident_candidate, root_cause_hypothesis


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


async def make_isolated_tenant():
    suffix = uuid4().hex
    tenant_id, department_id, customer_id, admin_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with async_session_maker() as db:
        db.add(Organization(id=tenant_id, name=f"Incident Tenant {suffix}", slug=f"incident-{suffix}"))
        await db.flush()
        db.add(Department(id=department_id, tenant_id=tenant_id, name=f"Networking {suffix}"))
        await db.flush()
        db.add_all([
            User(id=customer_id, tenant_id=tenant_id, email=f"customer-{suffix}@example.test", full_name="Customer", role="customer", public_role="customer", hashed_password=hash_password("x")),
            User(id=admin_id, tenant_id=tenant_id, email=f"admin-{suffix}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")),
        ])
        await db.commit()
    return tenant_id, department_id, customer_id, admin_id


async def teardown_tenant(tenant_id):
    from sqlalchemy import text
    async with async_session_maker() as db:
        await db.execute(text("DELETE FROM audit_logs WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("DELETE FROM notifications WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("DELETE FROM tickets WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("DELETE FROM incidents WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("DELETE FROM users WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("DELETE FROM departments WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("DELETE FROM organizations WHERE id=:t"), {"t": str(tenant_id)})
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_a_cluster_of_similar_tickets_creates_a_candidate_incident_and_links_them():
    tenant_id, department_id, customer_id, admin_id = await make_isolated_tenant()
    try:
        async with async_session_maker() as db:
            tickets = []
            for i in range(3):
                ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id,
                                 subject=f"VPN connection drops #{i}", description="The corporate VPN client disconnects repeatedly on Windows 11.",
                                 status="submitted", priority="medium", sentiment="neutral")
                db.add(ticket)
                tickets.append(ticket)
            await db.commit()
            for ticket in tickets:
                await db.refresh(ticket)

            incident = await detect_incident_candidate(db, tickets[-1])
            await db.commit()
            assert incident is not None
            assert incident.status == "candidate"
            assert incident.ticket_count == 3
            assert incident.department_id == department_id
            assert incident.category == "vpn"

            for ticket in tickets:
                await db.refresh(ticket)
                assert ticket.parent_incident_id == incident.id

        async with async_session_maker() as db:
            hypothesis = await root_cause_hypothesis(db, incident)
            assert hypothesis["status"] == "hypothesis"
            assert "not a confirmed root cause" in hypothesis["disclaimer"]
            assert hypothesis["ticket_count"] == 3
            assert len(hypothesis["supporting_ticket_ids"]) == 3
    finally:
        await teardown_tenant(tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_two_similar_tickets_below_threshold_do_not_create_an_incident():
    tenant_id, department_id, customer_id, admin_id = await make_isolated_tenant()
    try:
        async with async_session_maker() as db:
            tickets = []
            for i in range(2):
                ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id,
                                 subject=f"VPN connection drops #{i}", description="The corporate VPN client disconnects on Windows 11.",
                                 status="submitted", priority="medium", sentiment="neutral")
                db.add(ticket)
                tickets.append(ticket)
            await db.commit()
            for ticket in tickets:
                await db.refresh(ticket)
            incident = await detect_incident_candidate(db, tickets[-1])
            await db.commit()
            assert incident is None
    finally:
        await teardown_tenant(tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_confirm_requires_admin_capability_and_only_a_candidate_can_be_confirmed():
    tenant_id, department_id, customer_id, admin_id = await make_isolated_tenant()
    try:
        async with async_session_maker() as db:
            incident = Incident(tenant_id=tenant_id, department_id=department_id, category="vpn",
                                 title="Possible vpn incident", service="Networking", status="candidate",
                                 severity="high", ticket_count=3, growth_rate=0, common_symptom="vpn drops")
            db.add(incident)
            await db.commit()
            await db.refresh(incident)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            from app.core.security import create_access_token
            admin_token = create_access_token(admin_id, "system_admin", None, tenant_id)
            customer_token = create_access_token(customer_id, "customer", None, tenant_id)

            denied = await client.post(f"/api/incidents/{incident.id}/confirm", headers=auth(customer_token))
            assert denied.status_code == 403

            confirmed = await client.post(f"/api/incidents/{incident.id}/confirm", headers=auth(admin_token))
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["status"] == "investigating"
            assert confirmed.json()["confirmed_by"] == str(admin_id)

            again = await client.post(f"/api/incidents/{incident.id}/confirm", headers=auth(admin_token))
            assert again.status_code == 409
    finally:
        await teardown_tenant(tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_cross_tenant_incident_access_is_denied():
    tenant_a, department_a, customer_a, admin_a = await make_isolated_tenant()
    tenant_b, department_b, customer_b, admin_b = await make_isolated_tenant()
    try:
        async with async_session_maker() as db:
            incident = Incident(tenant_id=tenant_a, department_id=department_a, category="vpn",
                                 title="Tenant A incident", service="Networking", status="candidate",
                                 severity="high", ticket_count=3, growth_rate=0)
            db.add(incident)
            await db.commit()
            await db.refresh(incident)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            from app.core.security import create_access_token
            admin_b_token = create_access_token(admin_b, "system_admin", None, tenant_b)
            denied = await client.post(f"/api/incidents/{incident.id}/confirm", headers=auth(admin_b_token))
            assert denied.status_code == 404
            denied_read = await client.get(f"/api/incidents/{incident.id}/tickets", headers=auth(admin_b_token))
            assert denied_read.status_code == 404
    finally:
        await teardown_tenant(tenant_a)
        await teardown_tenant(tenant_b)


@pytest.mark.asyncio(loop_scope="session")
async def test_resolving_an_incident_only_posts_an_internal_safeguard_note_never_auto_resolves():
    tenant_id, department_id, customer_id, admin_id = await make_isolated_tenant()
    try:
        async with async_session_maker() as db:
            incident = Incident(tenant_id=tenant_id, department_id=department_id, category="vpn",
                                 title="Possible vpn incident", service="Networking", status="investigating",
                                 severity="high", ticket_count=1, growth_rate=0)
            db.add(incident)
            await db.flush()
            ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id,
                             subject="VPN drops", description="VPN keeps dropping.", status="in_progress",
                             priority="medium", sentiment="neutral", parent_incident_id=incident.id)
            db.add(ticket)
            await db.commit()
            await db.refresh(incident)
            incident_id = incident.id

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            from app.core.security import create_access_token
            admin_token = create_access_token(admin_id, "system_admin", None, tenant_id)
            resolved = await client.post(f"/api/incidents/{incident_id}/resolve", headers=auth(admin_token))
            assert resolved.status_code == 200, resolved.text
            assert resolved.json()["status"] == "resolved"

        async with async_session_maker() as db:
            refreshed_ticket = await db.get(Ticket, ticket.id)
            assert refreshed_ticket.status == "in_progress", "resolving an incident must never auto-resolve a linked ticket"
    finally:
        await teardown_tenant(tenant_id)
