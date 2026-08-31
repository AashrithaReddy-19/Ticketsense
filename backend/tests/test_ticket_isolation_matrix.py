from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import create_access_token, hash_password
from app.database import async_session_maker
from app.main import app
from app.models.department import Department
from app.models.platform import Organization
from app.models.ticket import Ticket
from app.models.user import User


@dataclass
class IsolationMatrix:
    tenant_ids: tuple[UUID, UUID]
    department_ids: tuple[UUID, UUID, UUID, UUID]
    user_ids: tuple[UUID, ...]
    ticket_ids: tuple[UUID, UUID, UUID, UUID]
    headers: dict[str, dict[str, str]]


def _headers(user_id: UUID, role: str, department_id: UUID | None, tenant_id: UUID):
    token = create_access_token(user_id, role, department_id, tenant_id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def isolation_matrix():
    tenant_a, tenant_b = uuid4(), uuid4()
    a_network, a_cloud, b_network, b_cloud = (uuid4() for _ in range(4))
    customer_a, customer_a_other, agent_a_network, agent_a_cloud, agent_b_network = (
        uuid4() for _ in range(5)
    )
    own_ticket, same_tenant_other, other_department, other_tenant = (uuid4() for _ in range(4))
    suffix = uuid4().hex
    password = hash_password("Isolation-Test-Only-123")

    async with async_session_maker() as db:
        db.add_all([
            Organization(id=tenant_a, name=f"Isolation Tenant A {suffix}", slug=f"iso-a-{suffix}"),
            Organization(id=tenant_b, name=f"Isolation Tenant B {suffix}", slug=f"iso-b-{suffix}"),
        ])
        await db.flush()
        db.add_all([
            Department(id=a_network, tenant_id=tenant_a, name=f"Networking A {suffix}"),
            Department(id=a_cloud, tenant_id=tenant_a, name=f"Cloud A {suffix}"),
            Department(id=b_network, tenant_id=tenant_b, name=f"Networking B {suffix}"),
            Department(id=b_cloud, tenant_id=tenant_b, name=f"Cloud B {suffix}"),
        ])
        await db.flush()
        db.add_all([
            User(id=customer_a, tenant_id=tenant_a, email=f"customer-a-{suffix}@example.test", full_name="Customer A", role="customer", hashed_password=password),
            User(id=customer_a_other, tenant_id=tenant_a, email=f"customer-a2-{suffix}@example.test", full_name="Customer A2", role="customer", hashed_password=password),
            User(id=agent_a_network, tenant_id=tenant_a, department_id=a_network, email=f"agent-an-{suffix}@example.test", full_name="Agent A Network", role="support_agent", hashed_password=password),
            User(id=agent_a_cloud, tenant_id=tenant_a, department_id=a_cloud, email=f"agent-ac-{suffix}@example.test", full_name="Agent A Cloud", role="support_agent", hashed_password=password),
            User(id=agent_b_network, tenant_id=tenant_b, department_id=b_network, email=f"agent-bn-{suffix}@example.test", full_name="Agent B Network", role="support_agent", hashed_password=password),
        ])
        await db.flush()
        db.add_all([
            Ticket(id=own_ticket, tenant_id=tenant_a, submitted_by=customer_a, department_id=a_network, subject="Owned network ticket", description="Customer A owns this network support ticket.", status="in_review", priority="high", sentiment="neutral", review_required=True),
            Ticket(id=same_tenant_other, tenant_id=tenant_a, submitted_by=customer_a_other, department_id=a_network, subject="Other customer network ticket", description="A different customer owns this support ticket.", status="in_review", priority="medium", sentiment="neutral", review_required=True),
            Ticket(id=other_department, tenant_id=tenant_a, submitted_by=customer_a_other, department_id=a_cloud, subject="Cloud department ticket", description="This ticket belongs to the Cloud department.", status="in_review", priority="medium", sentiment="neutral", review_required=True),
            Ticket(id=other_tenant, tenant_id=tenant_b, submitted_by=agent_b_network, department_id=b_network, subject="Other tenant network ticket", description="This ticket belongs to another tenant.", status="in_review", priority="medium", sentiment="neutral", review_required=True),
        ])
        await db.commit()

    matrix = IsolationMatrix(
        tenant_ids=(tenant_a, tenant_b),
        department_ids=(a_network, a_cloud, b_network, b_cloud),
        user_ids=(customer_a, customer_a_other, agent_a_network, agent_a_cloud, agent_b_network),
        ticket_ids=(own_ticket, same_tenant_other, other_department, other_tenant),
        headers={
            "customer_a": _headers(customer_a, "customer", None, tenant_a),
            "agent_a_network": _headers(agent_a_network, "support_agent", a_network, tenant_a),
            "agent_a_cloud": _headers(agent_a_cloud, "support_agent", a_cloud, tenant_a),
            "agent_b_network": _headers(agent_b_network, "support_agent", b_network, tenant_b),
        },
    )
    yield matrix

    async with async_session_maker() as db:
        await db.execute(delete(Ticket).where(Ticket.id.in_(matrix.ticket_ids)))
        await db.execute(delete(User).where(User.id.in_(matrix.user_ids)))
        await db.execute(delete(Department).where(Department.id.in_(matrix.department_ids)))
        await db.execute(delete(Organization).where(Organization.id.in_(matrix.tenant_ids)))
        await db.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def matrix_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio(loop_scope="session")
async def test_customer_ownership_isolation(matrix_client, isolation_matrix):
    own, same_tenant_other, _, other_tenant = isolation_matrix.ticket_ids
    headers = isolation_matrix.headers["customer_a"]
    assert (await matrix_client.get(f"/api/tickets/{own}", headers=headers)).status_code == 200
    assert (await matrix_client.get(f"/api/tickets/{same_tenant_other}", headers=headers)).status_code == 404
    assert (await matrix_client.get(f"/api/tickets/{other_tenant}", headers=headers)).status_code == 404
    visible = (await matrix_client.get("/api/tickets", headers=headers)).json()
    assert {row["id"] for row in visible} == {str(own)}


@pytest.mark.asyncio(loop_scope="session")
async def test_agent_department_and_tenant_isolation(matrix_client, isolation_matrix):
    own, same_dept, other_department, other_tenant = isolation_matrix.ticket_ids
    network = isolation_matrix.headers["agent_a_network"]
    cloud = isolation_matrix.headers["agent_a_cloud"]
    assert (await matrix_client.get(f"/api/tickets/{own}", headers=network)).status_code == 200
    assert (await matrix_client.get(f"/api/tickets/{same_dept}", headers=network)).status_code == 200
    assert (await matrix_client.get(f"/api/tickets/{other_department}", headers=network)).status_code == 404
    assert (await matrix_client.get(f"/api/tickets/{other_tenant}", headers=network)).status_code == 404
    assert (await matrix_client.get(f"/api/tickets/{other_department}", headers=cloud)).status_code == 200


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("suffix", ["", "/ai-analysis", "/evidence", "/similar", "/trace"])
async def test_cross_tenant_get_endpoints_deny(matrix_client, isolation_matrix, suffix):
    other_tenant = isolation_matrix.ticket_ids[3]
    response = await matrix_client.get(
        f"/api/tickets/{other_tenant}{suffix}",
        headers=isolation_matrix.headers["agent_a_network"],
    )
    assert response.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_cross_tenant_mutation_endpoints_deny(matrix_client, isolation_matrix):
    other_tenant = isolation_matrix.ticket_ids[3]
    headers = isolation_matrix.headers["agent_a_network"]
    action = await matrix_client.post(
        f"/api/tickets/{other_tenant}/action",
        headers=headers,
        json={"action": "resolve", "reason": "must be denied"},
    )
    feedback = await matrix_client.post(
        f"/api/tickets/{other_tenant}/feedback",
        headers=headers,
        json={"rating": 5, "resolved": True},
    )
    assert action.status_code == 404
    assert feedback.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_queue_isolation(matrix_client, isolation_matrix):
    own, same_dept, other_department, other_tenant = isolation_matrix.ticket_ids
    network_response = await matrix_client.get(
        "/api/queues/department_triage",
        headers=isolation_matrix.headers["agent_a_network"],
    )
    assert network_response.status_code == 200
    network_ids = {row["id"] for row in network_response.json()["items"]}
    assert {str(own), str(same_dept)} <= network_ids
    assert str(other_department) not in network_ids
    assert str(other_tenant) not in network_ids

    tenant_b_response = await matrix_client.get(
        "/api/queues/department_triage",
        headers=isolation_matrix.headers["agent_b_network"],
    )
    assert tenant_b_response.status_code == 200
    tenant_b_ids = {row["id"] for row in tenant_b_response.json()["items"]}
    assert str(other_tenant) in tenant_b_ids
    assert not ({str(own), str(same_dept), str(other_department)} & tenant_b_ids)
