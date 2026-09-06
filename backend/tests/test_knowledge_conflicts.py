"""Coverage for automatic knowledge-conflict detection (V2 Phase 10) and its
integration into the fail-closed auto-resolution gate: detectors must
compute real signals from real rows, detection must be idempotent (no
duplicate conflicts on repeated scans), and — the critical end-to-end
property — an open, high-severity conflict on cited evidence must actually
block auto-resolution via the new no_unresolved_knowledge_conflict gate,
with the block lifting only once a human resolves the conflict.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.database import async_session_maker
from app.main import app
from app.models.enterprise import ResolutionConfirmation
from app.models.feedback import Feedback
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.knowledge_conflict import KnowledgeConflict
from app.models.user import User
from app.services.knowledge_conflicts.detector import (
    blocking_article_ids, detect_contradictory_steps, detect_rate_based_conflicts, detect_unused_articles, run_all_detectors,
)
from app.services.resolution_policy import process_resolution_decision
from test_resolution_policy_and_assignment import make_grounded_draft, make_permissive_policy, make_ticket, scenario


def headers_for(user_id, role, department_id, tenant_id):
    from app.core.security import create_access_token
    return {"Authorization": f"Bearer {create_access_token(user_id, role, department_id, tenant_id)}"}


async def _approved_article(db, scenario, title, content):
    article = KnowledgeBaseDocument(tenant_id=scenario["tenant_id"], department_id=scenario["department_id"], title=title, content=content, status="approved", version="1.0", is_publishable=True)
    db.add(article)
    await db.flush()
    return article


@pytest.mark.asyncio(loop_scope="session")
async def test_contradictory_steps_detected_between_real_articles(scenario):
    async with async_session_maker() as db:
        await _approved_article(db, scenario, "VPN access policy A", "VPN access is required for all remote employees using the corporate gateway.")
        await _approved_article(db, scenario, "VPN access policy B", "VPN access is prohibited for all remote employees using the corporate gateway.")
        await db.commit()

        found = await detect_contradictory_steps(db, scenario["tenant_id"])
        await db.commit()
        assert len(found) == 1
        assert found[0].conflict_type == "contradictory_steps"
        assert found[0].severity == "high"
        assert found[0].review_state == "open"
        assert 0.0 <= float(found[0].confidence) <= 1.0  # regression: was previously unclamped and could exceed 1.0


@pytest.mark.asyncio(loop_scope="session")
async def test_detection_is_idempotent_across_repeated_scans(scenario):
    async with async_session_maker() as db:
        await _approved_article(db, scenario, "Remote access policy A", "You must enable remote access for all support staff on this server.")
        await _approved_article(db, scenario, "Remote access policy B", "You must disable remote access for all support staff on this server.")
        await db.commit()

        first_pass = await run_all_detectors(db, scenario["tenant_id"])
        await db.commit()
        second_pass = await run_all_detectors(db, scenario["tenant_id"])
        await db.commit()

        assert len(first_pass) >= 1
        assert len(second_pass) == 0  # nothing new — the same conflicts were already flagged and are not re-created

        total_rows = (await db.scalars(select(KnowledgeConflict).where(KnowledgeConflict.tenant_id == scenario["tenant_id"]))).all()
        assert len(total_rows) == len(first_pass)


@pytest.mark.asyncio(loop_scope="session")
async def test_low_customer_success_detected_from_real_confirmations(scenario):
    async with async_session_maker() as db:
        article = await _approved_article(db, scenario, "Flaky fix", "Try restarting the printer spooler service.")
        tickets = [await make_ticket(db, scenario, f"Printer issue {i}", "Printer not responding.") for i in range(4)]
        await db.commit()

        from app.services.workflow import create_draft
        reviewer = await db.get(User, scenario["engineer_id"])
        for i, ticket in enumerate(tickets):
            draft = await create_draft(db, ticket, reviewer, f"Restart the printer spooler service. [KB-{i}]", "engineer", "approved", citations=[{"citation_id": f"KB-{i}", "article_id": str(article.id), "article_version": "1.0"}])
            draft.is_final = True
            ticket.final_response_draft_id = draft.id
            db.add(ResolutionConfirmation(tenant_id=scenario["tenant_id"], ticket_id=ticket.id, user_id=scenario["customer_id"], outcome="needs_help"))  # 0/4 solved = 0% success rate
        await db.commit()

        found = await detect_rate_based_conflicts(db, scenario["tenant_id"])
        await db.commit()
        low_success = [c for c in found if c.conflict_type == "low_customer_success" and c.article_a_id == article.id]
        assert len(low_success) == 1
        assert low_success[0].severity == "high"  # 0% is well under the 25% harsher-severity threshold
        assert low_success[0].sample_size == 4


@pytest.mark.asyncio(loop_scope="session")
async def test_high_engineer_edit_rate_detected_from_real_feedback(scenario):
    async with async_session_maker() as db:
        article = await _approved_article(db, scenario, "Draft-heavy article", "Reset the modem by holding the power button.")
        tickets = [await make_ticket(db, scenario, f"Modem issue {i}", "Modem offline.") for i in range(3)]
        await db.commit()
        from app.services.workflow import create_draft
        reviewer = await db.get(User, scenario["engineer_id"])
        for i, ticket in enumerate(tickets):
            draft = await create_draft(db, ticket, reviewer, f"Reset the modem. [KB-{i}]", "engineer", "approved", citations=[{"citation_id": f"KB-{i}", "article_id": str(article.id), "article_version": "1.0"}])
            db.add(Feedback(ticket_id=ticket.id, reviewer_id=reviewer.id, action="edit", edited_reply="Completely rewritten response.", text_change_ratio=0.8))
        await db.commit()

        found = await detect_rate_based_conflicts(db, scenario["tenant_id"])
        await db.commit()
        edit_conflicts = [c for c in found if c.conflict_type == "high_engineer_edit_rate" and c.article_a_id == article.id]
        assert len(edit_conflicts) == 1
        assert edit_conflicts[0].sample_size == 3


@pytest.mark.asyncio(loop_scope="session")
async def test_unused_article_detected_for_old_uncited_article(scenario):
    async with async_session_maker() as db:
        article = await _approved_article(db, scenario, "Forgotten article", "An old, never-cited procedure.")
        article.created_at = datetime.now(timezone.utc) - timedelta(days=200)
        await db.commit()

        found = await detect_unused_articles(db, scenario["tenant_id"], min_age_days=90)
        await db.commit()
        unused = [c for c in found if c.article_a_id == article.id]
        assert len(unused) == 1
        assert unused[0].severity == "low"


@pytest.mark.asyncio(loop_scope="session")
async def test_only_open_high_severity_conflicts_block_evidence(scenario):
    async with async_session_maker() as db:
        article = await _approved_article(db, scenario, "Blocked article", "Some content.")
        await db.commit()

        conflict = KnowledgeConflict(tenant_id=scenario["tenant_id"], article_a_id=article.id, dedup_key="test-dedup-key-1", conflict_type="unused_long_period", severity="low", evidence_excerpt_a="x", review_state="open")
        db.add(conflict)
        await db.commit()
        assert await blocking_article_ids(db, scenario["tenant_id"], [article.id]) == set()  # low severity never blocks

        conflict.severity = "high"
        await db.commit()
        assert await blocking_article_ids(db, scenario["tenant_id"], [article.id]) == {str(article.id)}  # open + high blocks

        conflict.review_state = "resolved"
        await db.commit()
        assert await blocking_article_ids(db, scenario["tenant_id"], [article.id]) == set()  # resolved never blocks, regardless of severity


@pytest.mark.asyncio(loop_scope="session")
async def test_open_high_severity_conflict_actually_blocks_auto_resolution_end_to_end(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-kc-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.flush()
        await make_permissive_policy(db, scenario, category=None, allowlist=["vpn"], updated_by=admin_id)
        article = await _approved_article(db, scenario, "VPN reset guide", "Reset the cached VPN credentials and reconnect to the VPN client.")
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        # This evidence item carries a real article_id, matching what a real GraphRAG retrieval would attach.
        evidence = [{"citation_id": "KB-001", "chunk_text": "Reset the cached VPN credentials and reconnect to the VPN client.", "status": "approved", "is_publishable": True, "article_version": "1.0", "similarity": 0.91, "tenant_id": str(scenario["tenant_id"]), "department_id": str(scenario["department_id"]), "article_id": str(article.id)}]
        await make_grounded_draft(db, ticket, evidence=evidence)
        await db.commit()

        baseline = await process_resolution_decision(db, ticket, triggered_by=admin_id)
        await db.commit()
        assert baseline.decision == "auto_resolve", baseline.failed_gates  # confirms the scenario is otherwise fully permissive

        # Reset the ticket to re-run the decision cleanly (TicketDecision is unique per
        # ticket+pipeline_execution, so the prior decision must go too), then introduce a blocking conflict.
        from app.models.enterprise import TicketDecision
        from sqlalchemy import delete
        await db.execute(delete(TicketDecision).where(TicketDecision.ticket_id == ticket.id))
        ticket.status = "ai_processing"; ticket.resolution_type = None; ticket.resolved_at = None
        ticket.final_response_draft_id = None; ticket.last_auto_resolution_fingerprint = None
        conflict = KnowledgeConflict(tenant_id=scenario["tenant_id"], article_a_id=article.id, dedup_key="test-dedup-key-2", conflict_type="contradictory_steps", severity="critical", evidence_excerpt_a="conflicting text", review_state="open")
        db.add(conflict)
        await db.commit()

        blocked_decision = await process_resolution_decision(db, ticket, triggered_by=admin_id)
        await db.commit()
        assert blocked_decision.decision != "auto_resolve"
        assert "no_unresolved_knowledge_conflict" in blocked_decision.failed_gates

        # A human resolves the conflict; the same evidence is now usable again.
        conflict.review_state = "resolved"
        await db.execute(delete(TicketDecision).where(TicketDecision.ticket_id == ticket.id))
        ticket.status = "ai_processing"; ticket.resolution_type = None; ticket.resolved_at = None
        ticket.final_response_draft_id = None; ticket.last_auto_resolution_fingerprint = None
        await db.commit()

        recovered_decision = await process_resolution_decision(db, ticket, triggered_by=admin_id)
        await db.commit()
        assert recovered_decision.decision == "auto_resolve", recovered_decision.failed_gates
        assert "no_unresolved_knowledge_conflict" in recovered_decision.passed_gates


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_knowledge_conflict_endpoints_are_feature_flag_gated_then_work():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _login(client, "sysadmin@demo.com")
        headers = _auth(admin)
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        gated = await client.post("/api/v2/knowledge-conflicts/scan", headers=headers)
        assert gated.status_code == 404

        override = await client.post(
            "/api/v2/features/knowledge_conflict_detection/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "Knowledge conflict test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        try:
            scan = await client.post("/api/v2/knowledge-conflicts/scan", headers=headers)
            assert scan.status_code == 201, scan.text

            listing = await client.get("/api/v2/knowledge-conflicts", headers=headers)
            assert listing.status_code == 200
        finally:
            await client.delete(f"/api/v2/features/knowledge_conflict_detection/overrides/{override_id}", headers=headers)
            from sqlalchemy import text
            async with async_session_maker() as db:
                await db.execute(text("DELETE FROM knowledge_conflicts WHERE tenant_id=:t"), {"t": tenant_id})
                await db.commit()
