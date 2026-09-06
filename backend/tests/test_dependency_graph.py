"""Coverage for the tenant-isolated dependency graph (V2 Phase 7): building
real edges from existing relationships, and — most importantly — that
traversal never leaks across tenants, never exposes a since-unpublished
knowledge article, never lets a customer see another customer's ticket
through a shared incident, and always caps depth/result counts server-side
regardless of what's requested.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.database import async_session_maker
from app.main import app
from app.models.graph import GraphEdge, GraphNode
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import Incident, Organization
from app.models.user import User
from app.services.graph.builder import rebuild_tenant_graph, sync_ticket_graph
from app.services.graph.traversal import neighborhood
from test_resolution_policy_and_assignment import make_ticket, scenario, teardown_tenant


async def cleanup_incidents_and_articles(tenant_id) -> None:
    """teardown_tenant (in test_resolution_policy_and_assignment) predates
    Incident/KnowledgeBaseDocument rows in these graph tests and doesn't
    clean them up; both are referenced by FKs without ON DELETE CASCADE, so
    leaving them behind would break the scenario fixture's own teardown."""
    from sqlalchemy import text
    async with async_session_maker() as db:
        await db.execute(text("DELETE FROM knowledge_base WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("UPDATE tickets SET parent_incident_id=NULL WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.execute(text("DELETE FROM incidents WHERE tenant_id=:t"), {"t": str(tenant_id)})
        await db.commit()


class FakeUser:
    """A minimal stand-in matching the (role, tenant_id, id) surface the
    traversal service actually reads, for tests that don't need a real
    authenticated HTTP session."""
    def __init__(self, id, role, tenant_id):
        self.id = id
        self.role = role
        self.tenant_id = tenant_id


@pytest.mark.asyncio(loop_scope="session")
async def test_sync_ticket_graph_builds_real_department_and_customer_edges(scenario):
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes.")
        await db.commit()
        await sync_ticket_graph(db, ticket)
        await db.commit()

        ticket_node = await db.scalar(select(GraphNode).where(GraphNode.tenant_id == scenario["tenant_id"], GraphNode.node_type == "ticket", GraphNode.external_id == ticket.id))
        assert ticket_node is not None
        assert ticket_node.confirmed is True

        dept_edge = await db.scalar(select(GraphEdge).where(GraphEdge.tenant_id == scenario["tenant_id"], GraphEdge.source_node_id == ticket_node.id, GraphEdge.edge_type == "routed_to"))
        assert dept_edge is not None
        assert dept_edge.confirmed is True

        customer_edge = await db.scalar(select(GraphEdge).where(GraphEdge.tenant_id == scenario["tenant_id"], GraphEdge.source_node_id == ticket_node.id, GraphEdge.edge_type == "submitted_by"))
        assert customer_edge is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_incident_cluster_edge_is_unconfirmed_until_admin_confirms(scenario):
    try:
        async with async_session_maker() as db:
            incident = Incident(tenant_id=scenario["tenant_id"], department_id=scenario["department_id"], category="vpn", title="VPN outage cluster", service="VPN", status="candidate", severity="medium", detection_reason="3 tickets in the vpn category within 72 hours.")
            db.add(incident)
            await db.flush()
            ticket = await make_ticket(db, scenario, "VPN down again", "Cannot reach VPN gateway.")
            ticket.parent_incident_id = incident.id
            await db.commit()

            await sync_ticket_graph(db, ticket)
            await db.commit()

            edge = await db.scalar(select(GraphEdge).where(GraphEdge.tenant_id == scenario["tenant_id"], GraphEdge.edge_type == "clustered_into"))
            assert edge is not None
            assert edge.confirmed is False  # incident.confirmed_at is still null
            assert edge.provenance == "3 tickets in the vpn category within 72 hours."

            admin_id = uuid4()
            db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-graph-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
            await db.commit()
            incident.confirmed_by = admin_id
            incident.confirmed_at = datetime.now(timezone.utc)
            await db.commit()

            await sync_ticket_graph(db, ticket)
            await db.commit()
            await db.refresh(edge)
            assert edge.confirmed is True  # now reflects the real Admin confirmation
    finally:
        await cleanup_incidents_and_articles(scenario["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_neighborhood_never_crosses_tenants(scenario):
    other_tenant_id = uuid4()
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes.")
        await db.commit()
        await sync_ticket_graph(db, ticket)
        await db.commit()
        db.add(Organization(id=other_tenant_id, name=f"Other tenant {scenario['suffix']}", slug=f"other-tenant-{scenario['suffix']}"))
        await db.commit()

        other_tenant_admin = FakeUser(id=uuid4(), role="system_admin", tenant_id=other_tenant_id)
        cross_tenant_result = await neighborhood(db, other_tenant_admin, ticket.id)
        assert cross_tenant_result.nodes == []
        assert cross_tenant_result.edges == []

        same_tenant_admin = FakeUser(id=uuid4(), role="system_admin", tenant_id=scenario["tenant_id"])
        same_tenant_result = await neighborhood(db, same_tenant_admin, ticket.id)
        assert len(same_tenant_result.nodes) >= 1

    await teardown_tenant(other_tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_customer_cannot_reach_another_customers_ticket_or_identity(scenario):
    try:
        async with async_session_maker() as db:
            incident = Incident(tenant_id=scenario["tenant_id"], department_id=scenario["department_id"], category="vpn", title="VPN outage cluster", service="VPN", status="candidate", severity="medium")
            db.add(incident)
            await db.flush()

            ticket_a = await make_ticket(db, scenario, "My VPN is down", "Cannot connect from home.")
            ticket_a.parent_incident_id = incident.id
            other_customer_id = uuid4()
            db.add(User(id=other_customer_id, tenant_id=scenario["tenant_id"], email=f"othercust-{scenario['suffix']}@example.test", full_name="Other Customer", role="customer", public_role="customer", hashed_password=hash_password("x")))
            await db.flush()
            ticket_b = await make_ticket(db, scenario, "VPN broken for me too", "Also cannot connect.")
            ticket_b.submitted_by = other_customer_id
            ticket_b.parent_incident_id = incident.id
            await db.commit()

            await sync_ticket_graph(db, ticket_a)
            await sync_ticket_graph(db, ticket_b)
            await db.commit()

            customer_a = FakeUser(id=scenario["customer_id"], role="customer", tenant_id=scenario["tenant_id"])
            result = await neighborhood(db, customer_a, ticket_a.id, max_depth=3)  # even a deep request is capped

            node_types = {n["node_type"] for n in result.nodes}
            assert "customer" not in node_types  # not even the requester's own customer node is exposed
            other_ticket_labels = [n["label"] for n in result.nodes if n["node_type"] == "ticket" and n["external_id"] != ticket_a.id]
            assert other_ticket_labels == []  # never reaches ticket_b, even indirectly via the shared incident
            assert result.depth_reached <= 1  # customer depth is hard-capped regardless of the requested max_depth
    finally:
        await cleanup_incidents_and_articles(scenario["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_unpublished_article_is_excluded_despite_existing_graph_node(scenario):
    try:
        async with async_session_maker() as db:
            article = KnowledgeBaseDocument(tenant_id=scenario["tenant_id"], department_id=scenario["department_id"], title="VPN reset guide", content="Reset the VPN client cache.", status="approved", version="1.0", is_publishable=True)
            db.add(article)
            await db.flush()
            ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes.")
            await db.commit()

            from app.services.graph.builder import _get_or_create_edge, _get_or_create_node
            ticket_node = await sync_ticket_graph(db, ticket)
            article_node = await _get_or_create_node(db, scenario["tenant_id"], "knowledge_article", article.id, article.title, {}, "knowledge_base", True)
            await _get_or_create_edge(db, scenario["tenant_id"], ticket_node, article_node, "cites", None, "test citation", True, "response_drafts.citations")
            await db.commit()

            admin = FakeUser(id=uuid4(), role="system_admin", tenant_id=scenario["tenant_id"])
            before = await neighborhood(db, admin, ticket.id)
            assert any(n["node_type"] == "knowledge_article" for n in before.nodes)

            article.is_publishable = False
            await db.commit()

            after = await neighborhood(db, admin, ticket.id)
            assert not any(n["node_type"] == "knowledge_article" for n in after.nodes)  # live re-check, not the cached node
    finally:
        await cleanup_incidents_and_articles(scenario["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_rebuild_is_idempotent(scenario):
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes.")
        await db.commit()

        first = await rebuild_tenant_graph(db, scenario["tenant_id"])
        await db.commit()
        second = await rebuild_tenant_graph(db, scenario["tenant_id"])
        await db.commit()

        assert first["node_count"] == second["node_count"]
        assert first["edge_count"] == second["edge_count"]
        assert first["node_count"] >= 1


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_graph_endpoints_are_feature_flag_gated_then_return_real_shape():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _login(client, "sysadmin@demo.com")
        headers = _auth(admin)
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        tickets = await client.get("/api/tickets", headers=headers)
        assert tickets.status_code == 200 and tickets.json()
        ticket_id = tickets.json()[0]["id"]

        gated = await client.get(f"/api/v2/graph/tickets/{ticket_id}", headers=headers)
        assert gated.status_code == 404  # graphrag flag disabled by default

        override = await client.post(
            "/api/v2/features/graphrag/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "Graph endpoint test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        try:
            rebuild = await client.post("/api/v2/graph/rebuild", headers=headers)
            assert rebuild.status_code == 200, rebuild.text
            assert rebuild.json()["node_count"] >= 0

            result = await client.get(f"/api/v2/graph/tickets/{ticket_id}", headers=headers)
            assert result.status_code == 200, result.text
            body = result.json()
            assert set(body) == {"nodes", "edges", "truncated", "depth_reached", "disclaimer"}
            assert "inferred" in body["disclaimer"].lower()
        finally:
            await client.delete(f"/api/v2/features/graphrag/overrides/{override_id}", headers=headers)
            from sqlalchemy import text
            async with async_session_maker() as db:
                await db.execute(text("DELETE FROM graph_edges WHERE tenant_id=:t"), {"t": tenant_id})
                await db.execute(text("DELETE FROM graph_nodes WHERE tenant_id=:t"), {"t": tenant_id})
                await db.commit()
