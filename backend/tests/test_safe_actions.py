"""Section 19: safe action framework — allowlisting, confirmation, consent,
idempotency, approval, tenant/department scoping, and audit."""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.security import create_access_token, hash_password
from app.database import async_session_maker
from app.main import app
from app.models.department import Department
from app.models.enterprise import EngineerProfile
from app.models.platform import AuditLog, Integration, Organization
from app.models.response_draft import EngineerDepartment
from app.models.safe_action import SafeActionDefinition, SafeActionExecution
from app.models.ticket import Ticket
from app.models.user import User


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_tenant():
    suffix = uuid4().hex
    tenant_id, department_id = uuid4(), uuid4()
    customer_id, engineer_id, other_engineer_id, admin_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with async_session_maker() as db:
        db.add(Organization(id=tenant_id, name=f"SafeAction Tenant {suffix}", slug=f"safe-action-{suffix}"))
        await db.flush()
        db.add(Department(id=department_id, tenant_id=tenant_id, name=f"Networking {suffix}"))
        await db.flush()
        db.add_all([
            User(id=customer_id, tenant_id=tenant_id, email=f"customer-{suffix}@example.test", full_name="Customer", role="customer", public_role="customer", hashed_password=hash_password("x")),
            User(id=engineer_id, tenant_id=tenant_id, department_id=department_id, email=f"engineer-{suffix}@example.test", full_name="Engineer", role="support_agent", public_role="engineer", hashed_password=hash_password("x"), is_active=True, is_available=True),
            User(id=other_engineer_id, tenant_id=tenant_id, department_id=department_id, email=f"other-engineer-{suffix}@example.test", full_name="Other Engineer", role="support_agent", public_role="engineer", hashed_password=hash_password("x"), is_active=True, is_available=True),
            User(id=admin_id, tenant_id=tenant_id, email=f"admin-{suffix}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")),
        ])
        await db.flush()
        db.add(EngineerDepartment(user_id=engineer_id, department_id=department_id))
        db.add(EngineerProfile(user_id=engineer_id, tenant_id=tenant_id, availability_status="available", max_weighted_capacity=10.0))
        ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id, assignee_id=engineer_id,
                         subject="VPN check", description="VPN issue.", status="in_progress", priority="medium", sentiment="neutral")
        db.add(ticket)
        db.add(Integration(tenant_id=tenant_id, provider="jira", name="Jira", enabled=True))
        await db.commit()
        await db.refresh(ticket)
    return {"tenant_id": tenant_id, "department_id": department_id, "customer_id": customer_id, "engineer_id": engineer_id,
            "other_engineer_id": other_engineer_id, "admin_id": admin_id, "ticket_id": ticket.id}


async def teardown_tenant(tenant_id):
    async with async_session_maker() as db:
        t = str(tenant_id)
        await db.execute(text("DELETE FROM safe_action_approvals WHERE execution_id IN (SELECT id FROM safe_action_executions WHERE tenant_id=:t)"), {"t": t})
        await db.execute(text("DELETE FROM safe_action_results WHERE execution_id IN (SELECT id FROM safe_action_executions WHERE tenant_id=:t)"), {"t": t})
        await db.execute(text("DELETE FROM safe_action_executions WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM audit_logs WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM notifications WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM tickets WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM integrations WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM engineer_profiles WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM engineer_departments WHERE user_id IN (SELECT id FROM users WHERE tenant_id=:t)"), {"t": t})
        await db.execute(text("DELETE FROM users WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM departments WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM organizations WHERE id=:t"), {"t": t})
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_customer_cannot_list_or_execute_safe_actions():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            customer_token = create_access_token(tenant["customer_id"], "customer", None, tenant["tenant_id"])
            listed = await client.get("/api/safe-actions", headers=auth(customer_token))
            assert listed.status_code == 200 and listed.json() == [], "a customer must see zero executable actions"

            denied = await client.post("/api/safe-actions/check_service_status/execute", headers={**auth(customer_token), "Idempotency-Key": uuid4().hex},
                                        json={"parameters": {"service_name": "jira"}, "confirm": True})
            assert denied.status_code == 403
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_engineer_cannot_act_on_a_ticket_they_are_not_assigned_to():
    """A ticket already assigned to a different engineer is not even visible to
    this engineer via the department-triage queue (assignee must be null for
    that), so this correctly denies at the visibility layer (404) — a stronger
    guarantee than a bare 403 would be."""
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            other_token = create_access_token(tenant["other_engineer_id"], "support_agent", tenant["department_id"], tenant["tenant_id"])
            denied = await client.post("/api/safe-actions/resend_verification_notification/execute",
                                        headers={**auth(other_token), "Idempotency-Key": uuid4().hex},
                                        json={"parameters": {"ticket_id": str(tenant["ticket_id"])}, "ticket_id": str(tenant["ticket_id"]), "confirm": True})
            assert denied.status_code in (403, 404)

        async with async_session_maker() as db:
            ticket = await db.get(Ticket, tenant["ticket_id"])
            ticket.assignee_id = None
            await db.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            other_token = create_access_token(tenant["other_engineer_id"], "support_agent", tenant["department_id"], tenant["tenant_id"])
            still_denied = await client.post("/api/safe-actions/resend_verification_notification/execute",
                                              headers={**auth(other_token), "Idempotency-Key": uuid4().hex},
                                              json={"parameters": {"ticket_id": str(tenant["ticket_id"])}, "ticket_id": str(tenant["ticket_id"]), "confirm": True})
            assert still_denied.status_code == 403, "even once visible (unassigned), an engineer must not act on a ticket that isn't theirs"
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_cross_tenant_ticket_scoping_is_denied():
    tenant_a = await make_tenant()
    tenant_b = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            engineer_b_token = create_access_token(tenant_b["engineer_id"], "support_agent", tenant_b["department_id"], tenant_b["tenant_id"])
            denied = await client.post("/api/safe-actions/resend_verification_notification/execute",
                                        headers={**auth(engineer_b_token), "Idempotency-Key": uuid4().hex},
                                        json={"parameters": {"ticket_id": str(tenant_a["ticket_id"])}, "ticket_id": str(tenant_a["ticket_id"]), "confirm": True})
            assert denied.status_code == 404
    finally:
        await teardown_tenant(tenant_a["tenant_id"])
        await teardown_tenant(tenant_b["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_disabled_action_cannot_be_previewed_or_executed():
    tenant = await make_tenant()
    try:
        async with async_session_maker() as db:
            definition = await db.scalar(select(SafeActionDefinition).where(SafeActionDefinition.action_key == "check_service_status"))
            definition.enabled = False
            await db.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            preview = await client.post("/api/safe-actions/check_service_status/preview", headers=auth(admin_token), json={"parameters": {"service_name": "jira"}})
            assert preview.status_code == 403
            executed = await client.post("/api/safe-actions/check_service_status/execute", headers={**auth(admin_token), "Idempotency-Key": uuid4().hex},
                                          json={"parameters": {"service_name": "jira"}, "confirm": True})
            assert executed.status_code == 403
    finally:
        async with async_session_maker() as db:
            definition = await db.scalar(select(SafeActionDefinition).where(SafeActionDefinition.action_key == "check_service_status"))
            definition.enabled = True
            await db.commit()
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_invalid_parameters_are_rejected():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            missing = await client.post("/api/safe-actions/check_service_status/preview", headers=auth(admin_token), json={"parameters": {}})
            assert missing.status_code == 422
            bad_email = await client.post("/api/safe-actions/check_account_lock_status/preview", headers=auth(admin_token), json={"parameters": {"email": "not-an-email"}})
            assert bad_email.status_code == 422
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_preview_never_performs_the_action():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            preview = await client.post("/api/safe-actions/resend_verification_notification/preview", headers=auth(admin_token),
                                         json={"parameters": {"ticket_id": str(tenant["ticket_id"])}, "ticket_id": str(tenant["ticket_id"])})
            assert preview.status_code == 200, preview.text
            assert "No data is created" in preview.json()["would_not_do"]
        async with async_session_maker() as db:
            count = await db.scalar(select(SafeActionExecution).where(SafeActionExecution.tenant_id == tenant["tenant_id"]))
            assert count is None, "a preview must never create an execution row"
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_confirmation_is_required_before_execution():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            unconfirmed = await client.post("/api/safe-actions/resend_verification_notification/execute", headers={**auth(admin_token), "Idempotency-Key": uuid4().hex},
                                             json={"parameters": {"ticket_id": str(tenant["ticket_id"])}, "ticket_id": str(tenant["ticket_id"]), "confirm": False})
            assert unconfirmed.status_code == 422
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_idempotent_replay_returns_the_original_execution_and_prevents_duplication():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            key = uuid4().hex
            first = await client.post("/api/safe-actions/check_service_status/execute", headers={**auth(admin_token), "Idempotency-Key": key},
                                       json={"parameters": {"service_name": "jira"}, "confirm": True})
            assert first.status_code == 201, first.text
            assert first.json()["result"]["sandbox"] is True

            replay = await client.post("/api/safe-actions/check_service_status/execute", headers={**auth(admin_token), "Idempotency-Key": key},
                                        json={"parameters": {"service_name": "jira"}, "confirm": True})
            assert replay.status_code == 201
            assert replay.json()["id"] == first.json()["id"]

        async with async_session_maker() as db:
            rows = list((await db.scalars(select(SafeActionExecution).where(
                SafeActionExecution.tenant_id == tenant["tenant_id"], SafeActionExecution.idempotency_key == key))).all())
            assert len(rows) == 1, "an idempotent replay must never create a second execution row"
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_sandbox_result_is_clearly_labelled_and_audit_record_is_created():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            executed = await client.post("/api/safe-actions/check_service_status/execute", headers={**auth(admin_token), "Idempotency-Key": uuid4().hex},
                                          json={"parameters": {"service_name": "jira"}, "confirm": True})
            assert executed.status_code == 201, executed.text
            assert executed.json()["result"]["sandbox"] is True
            assert executed.json()["status"] == "succeeded"

        async with async_session_maker() as db:
            log = await db.scalar(select(AuditLog).where(AuditLog.tenant_id == tenant["tenant_id"], AuditLog.action == "safe_action.executed"))
            assert log is not None
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_account_lock_status_never_exposes_password_data():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            async with async_session_maker() as db:
                customer = await db.get(User, tenant["customer_id"])
                email = customer.email
            executed = await client.post("/api/safe-actions/check_account_lock_status/execute", headers={**auth(admin_token), "Idempotency-Key": uuid4().hex},
                                          json={"parameters": {"email": email}, "confirm": True})
            assert executed.status_code == 201, executed.text
            body_text = executed.text.lower()
            assert "hashed_password" not in body_text and "password" not in executed.json()["result"]["data"]
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_high_risk_action_requires_a_different_approver_before_executing():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            engineer_token = create_access_token(tenant["engineer_id"], "support_agent", tenant["department_id"], tenant["tenant_id"])
            async with async_session_maker() as db:
                customer = await db.get(User, tenant["customer_id"])
                email = customer.email

            requested = await client.post("/api/safe-actions/create_password_reset_request/execute", headers={**auth(engineer_token), "Idempotency-Key": uuid4().hex},
                                           json={"parameters": {"email": email}, "confirm": True, "customer_consent": True})
            assert requested.status_code == 201, requested.text
            assert requested.json()["status"] == "pending_approval"
            execution_id = requested.json()["id"]

            self_approve = await client.post(f"/api/safe-actions/executions/{execution_id}/approve", headers=auth(engineer_token))
            assert self_approve.status_code == 403, "the requester must not be able to approve their own high-risk action"

            approved = await client.post(f"/api/safe-actions/executions/{execution_id}/approve", headers=auth(admin_token))
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "succeeded"
            assert approved.json()["result"]["data"]["password_changed"] is False
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_execution_history_list_endpoint_is_not_shadowed_by_the_action_key_route():
    """Regression test: GET /api/safe-actions/executions and GET /api/safe-actions/{action_key}
    are both single-segment GET routes under the same prefix. Registering the
    catch-all {action_key} route first previously shadowed /executions entirely
    (FastAPI/Starlette matches in registration order) -- a live browser check
    caught this as a raw 404 from the Admin Safe Actions page; no mocked
    frontend test or backend test had ever called the real router for this
    exact path before."""
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            executed = await client.post("/api/safe-actions/check_service_status/execute", headers={**auth(admin_token), "Idempotency-Key": uuid4().hex},
                                          json={"parameters": {"service_name": "jira"}, "confirm": True})
            assert executed.status_code == 201, executed.text

            history = await client.get("/api/safe-actions/executions", headers=auth(admin_token))
            assert history.status_code == 200, history.text
            assert any(row["id"] == executed.json()["id"] for row in history.json())
    finally:
        await teardown_tenant(tenant["tenant_id"])
