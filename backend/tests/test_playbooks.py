"""Section 13: playbook lifecycle, matching, application, and the resolution-
policy gate interaction (a playbook can only ever add a restriction, never
bypass any other gate)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.database import async_session_maker
from app.main import app
from app.models.ai_draft import AIDraft
from app.models.ai_pipeline import PipelineExecution
from app.models.department import Department
from app.models.enterprise import EngineerProfile, EngineerSkill
from app.models.platform import Organization
from app.models.playbook import Playbook
from app.models.response_draft import EngineerDepartment
from app.models.ticket import Ticket
from app.models.user import User
from app.services.resolution_policy import process_resolution_decision
from app.services.playbooks import apply_playbook, match_playbook


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def playbook_payload(key: str, category: str, auto_eligible: bool = False) -> dict:
    return {
        "playbook_key": key, "title": "Test playbook", "category": category,
        "applicable_error_codes": ["test-999"],
        "clarification_questions": ["What happened?"], "evidence_requirements": ["Screenshot"],
        "diagnostic_steps_template": [{"title": "Check status", "instruction": "Verify the service is up.", "evidence_required": True}],
        "approved_actions": ["Check service status"], "safety_warnings": ["Never share credentials"],
        "resolution_template": "Resolved via test playbook.", "escalation_rules": ["Escalate if unresolved after 1 hour"],
        "auto_resolution_eligible": auto_eligible, "reason": "Test playbook for automated coverage",
    }


@pytest.mark.asyncio(loop_scope="session")
async def test_full_playbook_lifecycle_draft_approve_activate_version_supersede_deactivate(demo_playbooks):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        customer = await token(client, "customer@demo.com")
        key = f"test_playbook_{uuid4().hex[:8]}"

        denied = await client.post("/api/playbooks", headers=auth(customer), json=playbook_payload(key, "general_it"))
        assert denied.status_code == 403

        created = await client.post("/api/playbooks", headers=auth(admin), json=playbook_payload(key, "general_it"))
        assert created.status_code == 201, created.text
        demo_playbooks.append(created.json()["id"])
        assert created.json()["status"] == "draft" and created.json()["version"] == 1

        cannot_activate_yet = await client.post(f"/api/playbooks/{created.json()['id']}/activate", headers=auth(admin))
        assert cannot_activate_yet.status_code == 409

        approved = await client.post(f"/api/playbooks/{created.json()['id']}/approve", headers=auth(admin))
        assert approved.status_code == 200 and approved.json()["status"] == "approved"

        activated = await client.post(f"/api/playbooks/{created.json()['id']}/activate", headers=auth(admin))
        assert activated.status_code == 200 and activated.json()["status"] == "active"

        listed = await client.get("/api/playbooks", headers=auth(admin), params={"status_filter": "active"})
        assert any(row["id"] == created.json()["id"] for row in listed.json())

        # New version supersedes the active one once it, too, is approved and activated.
        v2 = await client.post(f"/api/playbooks/{created.json()['id']}/version", headers=auth(admin), json=playbook_payload(key, "general_it"))
        assert v2.status_code == 201, v2.text
        demo_playbooks.append(v2.json()["id"])
        assert v2.json()["version"] == 2
        await client.post(f"/api/playbooks/{v2.json()['id']}/approve", headers=auth(admin))
        activated_v2 = await client.post(f"/api/playbooks/{v2.json()['id']}/activate", headers=auth(admin))
        assert activated_v2.status_code == 200

        superseded = await client.get("/api/playbooks", headers=auth(admin), params={"status_filter": "superseded"})
        assert any(row["id"] == created.json()["id"] for row in superseded.json())
        assert superseded.json()[0]["superseded_by_id"] == v2.json()["id"] or any(
            row["id"] == created.json()["id"] and row["superseded_by_id"] == v2.json()["id"] for row in superseded.json()
        )

        deactivated = await client.post(f"/api/playbooks/{v2.json()['id']}/deactivate", headers=auth(admin))
        assert deactivated.status_code == 200 and deactivated.json()["status"] == "inactive"


@pytest.mark.asyncio(loop_scope="session")
async def test_matched_playbook_ineligible_for_auto_resolution_forces_human_review(demo_playbooks):
    """The resolution-policy gate must treat a matched, auto_resolution_eligible=False
    playbook as an additional blocking gate, even when every other gate would pass."""
    suffix = uuid4().hex
    tenant_id, department_id = uuid4(), uuid4()
    customer_id, engineer_id, admin_id = uuid4(), uuid4(), uuid4()
    async with async_session_maker() as db:
        db.add(Organization(id=tenant_id, name=f"Playbook Gate Tenant {suffix}", slug=f"playbook-gate-{suffix}"))
        await db.flush()
        db.add(Department(id=department_id, tenant_id=tenant_id, name=f"Networking {suffix}"))
        await db.flush()
        db.add_all([
            User(id=customer_id, tenant_id=tenant_id, email=f"customer-{suffix}@example.test", full_name="Customer", role="customer", public_role="customer", hashed_password=hash_password("x")),
            User(id=engineer_id, tenant_id=tenant_id, department_id=department_id, email=f"engineer-{suffix}@example.test", full_name="Engineer", role="support_agent", public_role="engineer", hashed_password=hash_password("x"), is_active=True, is_available=True, max_active_workload=10),
            User(id=admin_id, tenant_id=tenant_id, email=f"admin-{suffix}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")),
        ])
        await db.flush()
        db.add(EngineerDepartment(user_id=engineer_id, department_id=department_id))
        db.add(EngineerProfile(user_id=engineer_id, tenant_id=tenant_id, availability_status="available", max_weighted_capacity=10.0))
        db.add(EngineerSkill(tenant_id=tenant_id, user_id=engineer_id, department_id=department_id, specialization="VPN Engineer", skill_level="expert", is_primary=True))

        from app.models.enterprise import DepartmentResolutionPolicy
        db.add(DepartmentResolutionPolicy(tenant_id=tenant_id, department_id=None, category=None, risk_class=None, version=1,
                                           allow_auto_resolution=True, auto_resolve_threshold=0.0, minimum_citation_coverage=0.0,
                                           minimum_retrieval_score=0.0, minimum_classification_confidence=0.0, minimum_classification_margin=0.0,
                                           auto_resolution_allowlist=["vpn"], sensitive_category_denylist=[], is_active=True,
                                           updated_by=admin_id, reason="Permissive test policy"))

        playbook = Playbook(tenant_id=tenant_id, playbook_key="vpn_test_ineligible", title="VPN test (ineligible)", category="vpn",
                            version=1, status="active", auto_resolution_eligible=False, created_by=admin_id, approved_by=admin_id)
        db.add(playbook)
        await db.flush()
        demo_playbooks.append(str(playbook.id))

        ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id,
                         subject="VPN keeps disconnecting", description="The VPN client disconnects every few minutes on Windows 11.",
                         status="ai_processing", priority="medium", sentiment="neutral")
        db.add(ticket)
        await db.flush()

        evidence = [{"citation_id": "KB-001", "chunk_text": "Reset the cached VPN credentials and reconnect.",
                     "status": "approved", "is_publishable": True, "article_version": "1.0", "similarity": 0.9,
                     "tenant_id": str(tenant_id), "department_id": str(department_id)}]
        draft = AIDraft(tenant_id=tenant_id, ticket_id=ticket.id, department_id=department_id, article_version="1.0",
                         draft_text="Reset the cached VPN credentials and reconnect. [KB-001]", citations=[{"citation_id": "KB-001"}],
                         evidence=evidence, generation_status="ready", citation_validation_status="valid",
                         validation_details={"confidence_score": 0.95, "confidence_features": {"classification_probability": 0.95, "classification_margin": 0.5},
                                              "citation_coverage": 1.0, "valid": True, "grounding": {"blocked": False, "overall_status": "Grounded"}})
        db.add(draft)
        execution = PipelineExecution(tenant_id=tenant_id, ticket_id=ticket.id, pipeline_version="test-1.0", trigger_type="test",
                                       status="completed", started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
                                       fallback_used=False, correlation_id=uuid4())
        db.add(execution)
        await db.flush()
        draft.validation_details = {**draft.validation_details, "execution_id": str(execution.id)}
        await db.commit()

        matched = await match_playbook(db, ticket, category="vpn")
        assert matched is not None and matched.id == playbook.id

        decision = await process_resolution_decision(db, ticket)
        await db.commit()
        assert decision.decision != "auto_resolve", decision.failed_gates
        assert "playbook_compatible" in decision.failed_gates

    async with async_session_maker() as db:
        await db.execute(select(Ticket).where(Ticket.id == ticket.id))  # sanity: ticket still resolvable in a fresh session
        await db.execute(select(Playbook).where(Playbook.id == playbook.id))


@pytest.mark.asyncio(loop_scope="session")
async def test_engineer_can_apply_an_active_playbook_and_it_creates_a_real_diagnostic_plan(demo_tickets):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await token(client, "customer@demo.com")
        engineer = await token(client, "agent@demo.com")
        team_lead = await token(client, "teamlead@demo.com")
        engineer_profile = await client.get("/api/auth/me", headers=auth(engineer))

        created = await client.post("/api/tickets", headers=auth(customer), json={
            "subject": "Playbook application check", "description": "The corporate VPN client keeps dropping the connection.",
        })
        assert created.status_code == 201, created.text
        ticket_id = created.json()["id"]
        demo_tickets.append(ticket_id)
        await client.post(f"/api/tickets/{ticket_id}/assign", headers=auth(team_lead), json={"engineer_id": engineer_profile.json()["id"], "comment": "Assigning for playbook test"})

        async with async_session_maker() as db:
            playbook = await db.scalar(select(Playbook).where(Playbook.playbook_key == "vpn_connection_failure", Playbook.status == "active"))
            assert playbook is not None, "the seeded vpn_connection_failure playbook must exist and be active"
            assert playbook.diagnostic_steps_template, "seeded playbook must carry a real diagnostic steps template"

        recommendation = await client.get(f"/api/tickets/{ticket_id}/recommended-playbook", headers=auth(engineer))
        assert recommendation.status_code == 200, recommendation.text
        assert recommendation.json()["playbook_key"] == "vpn_connection_failure"

        denied = await client.post(f"/api/tickets/{ticket_id}/playbooks/{playbook.id}/apply", headers=auth(customer))
        assert denied.status_code == 403

        applied = await client.post(f"/api/tickets/{ticket_id}/playbooks/{playbook.id}/apply", headers=auth(engineer))
        assert applied.status_code == 201, applied.text
        assert applied.json()["step_count"] == len(playbook.diagnostic_steps_template)

        plan = await client.get(f"/api/tickets/{ticket_id}/diagnostic-plan", headers=auth(engineer))
        assert plan.status_code == 200
        assert plan.json()["id"] == applied.json()["diagnostic_plan_id"]
        assert len(plan.json()["steps"]) == len(playbook.diagnostic_steps_template)
