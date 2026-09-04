"""Proves the approved-historical-resolution retrieval source (Phase 9) never leaks
across tenants or departments, and that both evidence sources (knowledge base and
resolved tickets) stay correctly attributed by source_type."""
from uuid import uuid4

import pytest
import pytest_asyncio

from app.database import async_session_maker
from app.models.department import Department
from app.models.platform import Organization
from app.models.response_draft import ResponseDraft
from app.models.ticket import Ticket
from app.models.user import User


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def resolved_tickets():
    """Two tenants, each with one department and one resolved, indexed ticket."""
    suffix = uuid4().hex
    tenant_a, tenant_b = uuid4(), uuid4()
    dept_a, dept_b = uuid4(), uuid4()
    customer_a, customer_b = uuid4(), uuid4()

    async with async_session_maker() as db:
        db.add_all([
            Organization(id=tenant_a, name=f"Resolution Tenant A {suffix}", slug=f"res-a-{suffix}"),
            Organization(id=tenant_b, name=f"Resolution Tenant B {suffix}", slug=f"res-b-{suffix}"),
        ])
        await db.flush()
        db.add_all([
            Department(id=dept_a, tenant_id=tenant_a, name=f"Networking A {suffix}"),
            Department(id=dept_b, tenant_id=tenant_b, name=f"Networking B {suffix}"),
        ])
        db.add_all([
            User(id=customer_a, tenant_id=tenant_a, email=f"cust-a-{suffix}@example.test", full_name="Customer A", role="customer", hashed_password="x"),
            User(id=customer_b, tenant_id=tenant_b, email=f"cust-b-{suffix}@example.test", full_name="Customer B", role="customer", hashed_password="x"),
        ])
        await db.flush()

        ticket_a = Ticket(tenant_id=tenant_a, submitted_by=customer_a, department_id=dept_a, subject="VPN token expired", description="Cannot authenticate to the VPN gateway.", status="submitted")
        ticket_b = Ticket(tenant_id=tenant_b, submitted_by=customer_b, department_id=dept_b, subject="VPN token expired", description="Cannot authenticate to the VPN gateway.", status="submitted")
        db.add_all([ticket_a, ticket_b])
        await db.flush()

        draft_a = ResponseDraft(tenant_id=tenant_a, ticket_id=ticket_a.id, version_number=1, content="Clear the cached VPN token and reauthenticate through the corporate portal.", author_type="reviewer", status="approved", is_final=True)
        draft_b = ResponseDraft(tenant_id=tenant_b, ticket_id=ticket_b.id, version_number=1, content="Reissue the VPN certificate from the identity provider and reconnect.", author_type="reviewer", status="approved", is_final=True)
        db.add_all([draft_a, draft_b])
        await db.flush()

        # final_response, final_response_draft_id and status='resolved' must land together —
        # ck_tickets_resolved_has_response is checked per-statement, not deferred to commit.
        ticket_a.final_response, ticket_a.final_response_draft_id, ticket_a.status = draft_a.content, draft_a.id, "resolved"
        ticket_b.final_response, ticket_b.final_response_draft_id, ticket_b.status = draft_b.content, draft_b.id, "resolved"
        await db.commit()

        from ai.embeddings.resolution_index import index_resolution
        stored_a = await index_resolution(db, ticket_a)
        stored_b = await index_resolution(db, ticket_b)
        await db.commit()

    return {
        "tenant_a": str(tenant_a), "tenant_b": str(tenant_b),
        "dept_a": str(dept_a), "dept_b": str(dept_b),
        "ticket_a": str(ticket_a.id), "ticket_b": str(ticket_b.id),
        "stored": stored_a and stored_b,
    }


def _require_embeddings(resolved_tickets):
    if not resolved_tickets["stored"]:
        pytest.skip("sentence-transformers embedding backend unavailable in this environment")


@pytest.mark.asyncio(loop_scope="session")
async def test_resolution_retrieval_is_scoped_to_the_requesting_tenant_and_department(resolved_tickets):
    _require_embeddings(resolved_tickets)
    from ai.graph.nodes import retrieve_node

    result = await retrieve_node({
        "tenant_id": resolved_tickets["tenant_a"], "department_id": resolved_tickets["dept_a"],
        "subject": "VPN token expired", "description": "Cannot authenticate to the VPN gateway.",
        "article_version": "1.0", "ticket_id": "",
    })
    chunks = result["retrieved_chunks"]
    resolved = [c for c in chunks if c["source_type"] == "resolved_ticket"]

    assert resolved, "the tenant's own approved resolution should be retrievable"
    for chunk in resolved:
        assert chunk["tenant_id"] == resolved_tickets["tenant_a"]
        assert chunk["department_id"] == resolved_tickets["dept_a"]
        assert chunk["source_id"] != resolved_tickets["ticket_b"]
    assert resolved_tickets["ticket_b"] not in {c["source_id"] for c in resolved}


@pytest.mark.asyncio(loop_scope="session")
async def test_resolution_retrieval_never_returns_another_tenants_resolution(resolved_tickets):
    _require_embeddings(resolved_tickets)
    from ai.graph.nodes import retrieve_node

    result = await retrieve_node({
        "tenant_id": resolved_tickets["tenant_b"], "department_id": resolved_tickets["dept_b"],
        "subject": "VPN token expired", "description": "Cannot authenticate to the VPN gateway.",
        "article_version": "1.0", "ticket_id": "",
    })
    resolved = [c for c in result["retrieved_chunks"] if c["source_type"] == "resolved_ticket"]
    source_ids = {c["source_id"] for c in resolved}
    assert resolved_tickets["ticket_a"] not in source_ids
    assert all(c["tenant_id"] == resolved_tickets["tenant_b"] for c in resolved)


@pytest.mark.asyncio(loop_scope="session")
async def test_resolution_retrieval_excludes_a_department_with_no_matching_scope(resolved_tickets):
    _require_embeddings(resolved_tickets)
    from ai.graph.nodes import retrieve_node

    result = await retrieve_node({
        "tenant_id": resolved_tickets["tenant_a"], "department_id": resolved_tickets["dept_b"],
        "subject": "VPN token expired", "description": "Cannot authenticate to the VPN gateway.",
        "article_version": "1.0", "ticket_id": "",
    })
    resolved = [c for c in result["retrieved_chunks"] if c["source_type"] == "resolved_ticket"]
    assert not resolved, "a tenant/department combination that owns no resolution must retrieve none"


@pytest.mark.asyncio(loop_scope="session")
async def test_resolution_citation_ids_use_a_distinct_rt_prefix_and_never_collide_with_kb(resolved_tickets):
    _require_embeddings(resolved_tickets)
    from ai.graph.nodes import retrieve_node

    result = await retrieve_node({
        "tenant_id": resolved_tickets["tenant_a"], "department_id": resolved_tickets["dept_a"],
        "subject": "VPN token expired", "description": "Cannot authenticate to the VPN gateway.",
        "article_version": "1.0", "ticket_id": "",
    })
    for chunk in result["retrieved_chunks"]:
        prefix = chunk["citation_id"].split("-")[0]
        assert prefix == ("RT" if chunk["source_type"] == "resolved_ticket" else "KB")
