"""Coverage for the immutable Resolution Passport (V2 Phase 5): creation on
both the AI auto-resolution path and the human-engineer approval path,
integrity hashing/tamper detection, supersession on re-resolution, the
customer-safe view, and legacy-ticket backfill.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.security import create_access_token, hash_password
from app.database import async_session_maker
from app.main import app
from app.models.enterprise import ResolutionConfirmation
from app.models.resolution_passport import ResolutionPassport
from app.models.response_draft import ResponseDraft
from app.models.user import User
from app.services.passport import recompute_integrity_hash
from app.services.resolution_policy import process_resolution_decision
from app.services.workflow import approve_draft, create_draft
from test_resolution_policy_and_assignment import make_grounded_draft, make_permissive_policy, make_ticket, scenario


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def headers_for(user_id: UUID, role: str, department_id, tenant_id) -> dict[str, str]:
    return auth(create_access_token(user_id, role, department_id, tenant_id))


@pytest.mark.asyncio(loop_scope="session")
async def test_auto_resolution_creates_immutable_passport_with_real_gate_snapshot(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.flush()
        await make_permissive_policy(db, scenario, category=None, allowlist=["vpn"], updated_by=admin_id)
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        await make_grounded_draft(db, ticket)
        await db.commit()

        decision = await process_resolution_decision(db, ticket, triggered_by=admin_id)
        await db.commit()
        await db.refresh(ticket)
        assert decision.decision == "auto_resolve"

        passport = await db.scalar(select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id))
        assert passport is not None
        assert passport.is_current is True
        assert passport.resolution_type == "ai"
        assert passport.response_draft_id == ticket.final_response_draft_id
        assert float(passport.overall_confidence) == decision.overall_confidence
        assert passport.passed_gates == decision.passed_gates
        assert passport.failed_gates == []
        assert len(passport.confidence_components) == 19
        assert passport.citations == [{"citation_id": "KB-001"}]
        assert passport.integrity_hash == recompute_integrity_hash(passport)
        assert passport.created_by == admin_id


@pytest.mark.asyncio(loop_scope="session")
async def test_engineer_approval_sets_resolution_type_and_records_edit_ratio(scenario):
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        await make_grounded_draft(db, ticket)
        await db.commit()
        reviewer = await db.get(User, scenario["engineer_id"])
        original = await create_draft(db, ticket, reviewer, "Reset the VPN client cache. [KB-001]", "engineer", "submitted_for_review", citations=[{"citation_id": "KB-001"}])
        ticket.status = "pending_review"
        await db.commit()

        approved = await approve_draft(
            db, ticket, reviewer, original,
            "Clear the VPN client's cached credentials, then reconnect using the corporate gateway profile. [KB-001]",
            "Verified against KB-001.", modified=True,
        )
        await db.commit()
        await db.refresh(ticket)

        assert ticket.resolution_type == "engineer"  # regression: v1 never set this on the human path
        passport = await db.scalar(select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id))
        assert passport is not None
        assert passport.resolution_type == "engineer"
        assert passport.ticket_decision_id is None  # no TicketDecision exists on the human path
        assert passport.response_draft_id == approved.id
        assert passport.engineer_edit_ratio is not None and passport.engineer_edit_ratio > 0
        assert passport.reviewer_id == scenario["engineer_id"]
        assert passport.feedback_id is not None
        assert passport.integrity_hash == recompute_integrity_hash(passport)


@pytest.mark.asyncio(loop_scope="session")
async def test_reresolution_supersedes_prior_passport_without_mutating_it(scenario):
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        await make_grounded_draft(db, ticket)
        await db.commit()
        reviewer = await db.get(User, scenario["engineer_id"])
        first_draft = await create_draft(db, ticket, reviewer, "Reset the cached VPN credentials and reconnect to the VPN client. [KB-001]", "engineer", "submitted_for_review", citations=[{"citation_id": "KB-001"}])
        ticket.status = "pending_review"
        await db.commit()
        await approve_draft(db, ticket, reviewer, first_draft, None, "First pass.", modified=False)
        await db.commit()

        first = await db.scalar(select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id, ResolutionPassport.is_current.is_(True)))
        assert first is not None
        first_hash = first.integrity_hash

        # Simulate a customer reopen and a second, independent resolution.
        second_draft = await create_draft(db, ticket, reviewer, "Reset the cached VPN credentials again and reconnect to the VPN client using the backup gateway. [KB-001]", "engineer", "submitted_for_review", citations=[{"citation_id": "KB-001"}])
        ticket.status = "pending_review"
        await db.commit()
        await approve_draft(db, ticket, reviewer, second_draft, None, "Second pass after reopen.", modified=False)
        await db.commit()

        await db.refresh(first)
        second = await db.scalar(select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id, ResolutionPassport.is_current.is_(True)))
        assert second.id != first.id
        assert first.is_current is False
        assert first.integrity_hash == first_hash  # superseding never rewrites the original row's own hash
        assert second.supersedes_passport_id == first.id
        assert second.previous_passport_hash == first_hash

        all_for_ticket = (await db.scalars(select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id))).all()
        assert len(all_for_ticket) == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_integrity_hash_detects_direct_tampering(scenario):
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        await make_grounded_draft(db, ticket)
        await db.commit()
        reviewer = await db.get(User, scenario["engineer_id"])
        draft = await create_draft(db, ticket, reviewer, "Reset the VPN client cache. [KB-001]", "engineer", "submitted_for_review", citations=[{"citation_id": "KB-001"}])
        ticket.status = "pending_review"
        await db.commit()
        await approve_draft(db, ticket, reviewer, draft, None, "Looks good.", modified=False)
        await db.commit()

        passport = await db.scalar(select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id))
        assert recompute_integrity_hash(passport) == passport.integrity_hash
        passport_id = passport.id

        # Bypass the ORM entirely to prove the hash isn't just trusting whatever's in memory.
        await db.execute(text("UPDATE resolution_passports SET overall_confidence = 0.01 WHERE id = :id"), {"id": str(passport_id)})
        await db.commit()

    async with async_session_maker() as fresh_db:  # a fresh session avoids reading back the stale identity-mapped object
        tampered = await fresh_db.get(ResolutionPassport, passport_id)
        assert recompute_integrity_hash(tampered) != tampered.integrity_hash


@pytest.mark.asyncio(loop_scope="session")
async def test_backfill_creates_passport_for_legacy_ticket_and_is_idempotent(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin3-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        ticket = await make_ticket(db, scenario, "Legacy resolved ticket", "Resolved before Resolution Passports existed.")
        await make_grounded_draft(db, ticket)
        reviewer = await db.get(User, scenario["engineer_id"])
        draft = await create_draft(db, ticket, reviewer, "Reset the cached VPN credentials and reconnect to the VPN client. [KB-001]", "engineer", "approved", citations=[{"citation_id": "KB-001"}])
        draft.is_final = True
        ticket.final_response = draft.content
        ticket.final_response_draft_id = draft.id
        ticket.resolution_type = "engineer"
        ticket.status = "resolved"
        ticket.resolved_at = datetime.now(timezone.utc)
        await db.commit()

        headers = headers_for(admin_id, "system_admin", None, scenario["tenant_id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        override = await client.post(
            "/api/v2/features/resolution_passport/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": str(scenario["tenant_id"]), "enabled": True, "rollout_percentage": 100, "reason": "Passport backfill test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        try:
            first_pass = await client.post("/api/v2/passports/backfill", headers=headers)
            assert first_pass.status_code == 200, first_pass.text
            assert first_pass.json()["created"] >= 1

            async with async_session_maker() as db:
                passport = await db.scalar(select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id))
                assert passport is not None
                assert passport.is_backfilled is True

            second_pass = await client.post("/api/v2/passports/backfill", headers=headers)
            assert second_pass.status_code == 200
            assert second_pass.json()["created"] == 0
            assert second_pass.json()["skipped"] >= 1
        finally:
            await client.delete(f"/api/v2/features/resolution_passport/overrides/{override_id}", headers=headers)


@pytest.mark.asyncio(loop_scope="session")
async def test_customer_view_hides_internal_scores_and_reflects_confirmation(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin2-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.flush()
        await make_permissive_policy(db, scenario, category=None, allowlist=["vpn"], updated_by=admin_id)
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        await make_grounded_draft(db, ticket)
        await db.commit()
        await process_resolution_decision(db, ticket, triggered_by=admin_id)
        await db.commit()
        customer_headers = headers_for(scenario["customer_id"], "customer", None, scenario["tenant_id"])
        admin_headers = headers_for(admin_id, "system_admin", None, scenario["tenant_id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        override = await client.post(
            "/api/v2/features/resolution_passport/overrides", headers=admin_headers,
            json={"scope_type": "tenant", "scope_value": str(scenario["tenant_id"]), "enabled": True, "rollout_percentage": 100, "reason": "Customer view test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        try:
            async with async_session_maker() as db:
                ticket_id = str(await db.scalar(select(ResolutionPassport.ticket_id).where(ResolutionPassport.tenant_id == scenario["tenant_id"])))

            response = await client.get(f"/api/v2/passports/{ticket_id}", headers=customer_headers)
            assert response.status_code == 200, response.text
            body = response.json()
            assert set(body) == {"ticket_id", "resolution_type", "public_citations", "confirmation_state", "integrity_verified", "created_at"}
            assert body["confirmation_state"] == "pending"
            assert body["integrity_verified"] is True

            async with async_session_maker() as db:
                db.add(ResolutionConfirmation(tenant_id=scenario["tenant_id"], ticket_id=UUID(ticket_id), user_id=scenario["customer_id"], outcome="solved"))
                await db.commit()

            after_confirm = await client.get(f"/api/v2/passports/{ticket_id}", headers=customer_headers)
            assert after_confirm.json()["confirmation_state"] == "solved"

            internal = await client.get(f"/api/v2/passports/{ticket_id}", headers=admin_headers)
            assert internal.status_code == 200
            assert "overall_confidence" in internal.json()
            assert "confidence_components" in internal.json()
        finally:
            await client.delete(f"/api/v2/features/resolution_passport/overrides/{override_id}", headers=admin_headers)


@pytest.mark.asyncio(loop_scope="session")
async def test_passport_endpoint_is_feature_flag_gated():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        me = await client.get("/api/auth/me", headers=auth(admin))
        tickets = await client.get("/api/tickets", headers=auth(admin))
        any_ticket_id = tickets.json()[0]["id"] if tickets.status_code == 200 and tickets.json() else None
        if any_ticket_id:
            gated = await client.get(f"/api/v2/passports/{any_ticket_id}", headers=auth(admin))
            assert gated.status_code == 404
