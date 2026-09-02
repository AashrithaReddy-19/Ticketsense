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
from app.models.ticket_attachment import TicketAttachment
from app.models.user import User


@dataclass
class AttachmentFixture:
    tenant_ids: tuple[UUID, UUID]
    department_ids: tuple[UUID, UUID]
    user_ids: tuple[UUID, ...]
    ticket_ids: tuple[UUID, UUID]
    headers: dict[str, dict[str, str]]


def _headers(user_id: UUID, role: str, department_id: UUID | None, tenant_id: UUID):
    token = create_access_token(user_id, role, department_id, tenant_id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def attachment_fixture():
    tenant_a, tenant_b = uuid4(), uuid4()
    dept_a_network, dept_a_cloud, dept_b_network = uuid4(), uuid4(), uuid4()
    customer_a, agent_a_network, agent_a_cloud, agent_b_network, auditor_a = (uuid4() for _ in range(5))
    ticket_a, ticket_b = uuid4(), uuid4()
    suffix = uuid4().hex
    password = hash_password("Attachment-Test-Only-123")

    async with async_session_maker() as db:
        db.add_all([
            Organization(id=tenant_a, name=f"Attachment Tenant A {suffix}", slug=f"attach-a-{suffix}"),
            Organization(id=tenant_b, name=f"Attachment Tenant B {suffix}", slug=f"attach-b-{suffix}"),
        ])
        await db.flush()
        db.add_all([
            Department(id=dept_a_network, tenant_id=tenant_a, name=f"Networking A {suffix}"),
            Department(id=dept_a_cloud, tenant_id=tenant_a, name=f"Cloud A {suffix}"),
            Department(id=dept_b_network, tenant_id=tenant_b, name=f"Networking B {suffix}"),
        ])
        await db.flush()
        db.add_all([
            User(id=customer_a, tenant_id=tenant_a, email=f"attach-customer-{suffix}@example.com", full_name="Attach Customer", role="customer", hashed_password=password),
            User(id=agent_a_network, tenant_id=tenant_a, department_id=dept_a_network, email=f"attach-agent-an-{suffix}@example.com", full_name="Attach Agent AN", role="support_agent", hashed_password=password),
            User(id=agent_a_cloud, tenant_id=tenant_a, department_id=dept_a_cloud, email=f"attach-agent-ac-{suffix}@example.com", full_name="Attach Agent AC", role="support_agent", hashed_password=password),
            User(id=agent_b_network, tenant_id=tenant_b, department_id=dept_b_network, email=f"attach-agent-bn-{suffix}@example.com", full_name="Attach Agent BN", role="support_agent", hashed_password=password),
            User(id=auditor_a, tenant_id=tenant_a, email=f"attach-auditor-{suffix}@example.com", full_name="Attach Auditor", role="auditor", hashed_password=password),
        ])
        await db.flush()
        db.add_all([
            Ticket(id=ticket_a, tenant_id=tenant_a, submitted_by=customer_a, department_id=dept_a_network, subject="VPN fails after reset", description="VPN authentication fails after a password reset.", status="in_review", priority="medium", sentiment="neutral", review_required=True),
            Ticket(id=ticket_b, tenant_id=tenant_b, submitted_by=agent_b_network, department_id=dept_b_network, subject="Other tenant ticket", description="Belongs to another tenant entirely.", status="in_review", priority="medium", sentiment="neutral", review_required=True),
        ])
        await db.commit()

    fixture = AttachmentFixture(
        tenant_ids=(tenant_a, tenant_b),
        department_ids=(dept_a_network, dept_a_cloud),
        user_ids=(customer_a, agent_a_network, agent_a_cloud, agent_b_network, auditor_a),
        ticket_ids=(ticket_a, ticket_b),
        headers={
            "customer_a": _headers(customer_a, "customer", None, tenant_a),
            "agent_a_network": _headers(agent_a_network, "support_agent", dept_a_network, tenant_a),
            "agent_a_cloud": _headers(agent_a_cloud, "support_agent", dept_a_cloud, tenant_a),
            "agent_b_network": _headers(agent_b_network, "support_agent", dept_b_network, tenant_b),
            "auditor_a": _headers(auditor_a, "auditor", None, tenant_a),
        },
    )
    yield fixture

    async with async_session_maker() as db:
        await db.execute(delete(TicketAttachment).where(TicketAttachment.ticket_id.in_(fixture.ticket_ids)))
        await db.execute(delete(Ticket).where(Ticket.id.in_(fixture.ticket_ids)))
        await db.execute(delete(User).where(User.id.in_(fixture.user_ids)))
        await db.execute(delete(Department).where(Department.id.in_(fixture.department_ids + (dept_b_network,))))
        await db.execute(delete(Organization).where(Organization.id.in_(fixture.tenant_ids)))
        await db.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def attachment_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _txt(name: str, content: bytes = b"VPN authentication failed after password reset."):
    return {"file": (name, content, "text/plain")}


@pytest.mark.asyncio(loop_scope="session")
async def test_customer_can_upload_and_sees_no_internal_fields(attachment_client, attachment_fixture):
    ticket_a, _ = attachment_fixture.ticket_ids
    headers = attachment_fixture.headers["customer_a"]
    upload = await attachment_client.post(f"/api/tickets/{ticket_a}/attachment", headers=headers, files=_txt("evidence.txt"))
    assert upload.status_code == 201
    body = upload.json()
    assert "sanitized_text" not in body and "ocr_confidence" not in body and "extraction_method" not in body

    fetched = await attachment_client.get(f"/api/tickets/{ticket_a}/attachment", headers=headers)
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert "sanitized_text" not in fetched_body and "warnings" not in fetched_body


@pytest.mark.asyncio(loop_scope="session")
async def test_customer_cannot_process_or_view_internal_ai(attachment_client, attachment_fixture):
    ticket_a, _ = attachment_fixture.ticket_ids
    headers = attachment_fixture.headers["customer_a"]
    process = await attachment_client.post(f"/api/tickets/{ticket_a}/attachment/process", headers=headers)
    assert process.status_code == 403
    draft = await attachment_client.get(f"/api/tickets/{ticket_a}/ai-draft", headers=headers)
    assert draft.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_engineer_sees_internal_fields_after_processing_and_retry_is_idempotent(attachment_client, attachment_fixture):
    ticket_a, _ = attachment_fixture.ticket_ids
    headers = attachment_fixture.headers["agent_a_network"]
    first = await attachment_client.post(f"/api/tickets/{ticket_a}/attachment/process", headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["extraction_status"] == "ready"
    assert first_body["sanitized_text"] == "VPN authentication failed after password reset."
    assert first_body["ocr_confidence_available"] is False and first_body["ocr_confidence"] is None

    second = await attachment_client.post(f"/api/tickets/{ticket_a}/attachment/process", headers=headers)
    assert second.status_code == 200
    assert second.json()["id"] == first_body["id"]

    async with async_session_maker() as db:
        from sqlalchemy import select
        rows = (await db.execute(select(TicketAttachment).where(TicketAttachment.ticket_id == ticket_a))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_cross_tenant_and_cross_department_attachment_access_denied(attachment_client, attachment_fixture):
    ticket_a, _ = attachment_fixture.ticket_ids
    cross_tenant = await attachment_client.get(f"/api/tickets/{ticket_a}/attachment", headers=attachment_fixture.headers["agent_b_network"])
    assert cross_tenant.status_code == 404
    cross_department = await attachment_client.get(f"/api/tickets/{ticket_a}/attachment", headers=attachment_fixture.headers["agent_a_cloud"])
    assert cross_department.status_code == 404
    cross_tenant_download = await attachment_client.get(f"/api/tickets/{ticket_a}/attachment/download", headers=attachment_fixture.headers["agent_b_network"])
    assert cross_tenant_download.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_auditor_cannot_mutate_attachment(attachment_client, attachment_fixture):
    ticket_a, _ = attachment_fixture.ticket_ids
    headers = attachment_fixture.headers["auditor_a"]
    upload = await attachment_client.post(f"/api/tickets/{ticket_a}/attachment", headers=headers, files=_txt("second.txt"))
    assert upload.status_code == 403
    process = await attachment_client.post(f"/api/tickets/{ticket_a}/attachment/process", headers=headers)
    assert process.status_code == 403
    delete_resp = await attachment_client.delete(f"/api/tickets/{ticket_a}/attachment", headers=headers)
    assert delete_resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_secure_download_returns_content_and_denies_unsupported_upload(attachment_client, attachment_fixture):
    ticket_a, _ = attachment_fixture.ticket_ids
    headers = attachment_fixture.headers["agent_a_network"]
    download = await attachment_client.get(f"/api/tickets/{ticket_a}/attachment/download", headers=headers)
    assert download.status_code == 200
    assert download.content == b"VPN authentication failed after password reset."
    assert download.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio(loop_scope="session")
async def test_ticket_without_attachment_returns_404_and_does_not_break_ticket_read(attachment_client, attachment_fixture):
    _, ticket_b = attachment_fixture.ticket_ids
    headers = attachment_fixture.headers["agent_b_network"]
    missing = await attachment_client.get(f"/api/tickets/{ticket_b}/attachment", headers=headers)
    assert missing.status_code == 404
    ticket = await attachment_client.get(f"/api/tickets/{ticket_b}", headers=headers)
    assert ticket.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_unsupported_upload_rejected_via_api(attachment_client, attachment_fixture):
    _, ticket_b = attachment_fixture.ticket_ids
    headers = attachment_fixture.headers["agent_b_network"]
    rejected = await attachment_client.post(f"/api/tickets/{ticket_b}/attachment", headers=headers, files={"file": ("run.exe", b"MZ-fake-binary", "application/octet-stream")})
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "unsupported_extension"
