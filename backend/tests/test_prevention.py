"""Section 20: predictive-prevention recommendations — tenant isolation, minimum
evidence thresholds, correct supporting counts, no-PII evidence, admin-only
review actions, knowledge-draft conversion, incident linking, and dismissal
audit history."""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.security import create_access_token, hash_password
from app.database import async_session_maker
from app.main import app
from app.models.department import Department
from app.models.platform import KnowledgeArticle, Organization
from app.models.prevention import PreventionRecommendation, RecommendationAction, RecommendationEvidence
from app.models.ticket import Ticket
from app.models.user import User
from app.services.prevention import MIN_REPEATED_CATEGORY_TICKETS, generate_recommendations


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_tenant():
    suffix = uuid4().hex
    tenant_id, department_id = uuid4(), uuid4()
    customer_id, admin_id = uuid4(), uuid4()
    async with async_session_maker() as db:
        db.add(Organization(id=tenant_id, name=f"Prevention Tenant {suffix}", slug=f"prevention-{suffix}"))
        await db.flush()
        db.add(Department(id=department_id, tenant_id=tenant_id, name=f"Networking {suffix}"))
        await db.flush()
        db.add_all([
            User(id=customer_id, tenant_id=tenant_id, email=f"customer-{suffix}@example.test", full_name="Customer", role="customer", public_role="customer", hashed_password=hash_password("x")),
            User(id=admin_id, tenant_id=tenant_id, email=f"admin-{suffix}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")),
        ])
        await db.commit()
    return {"tenant_id": tenant_id, "department_id": department_id, "customer_id": customer_id, "admin_id": admin_id}


async def make_tickets(tenant, count: int, subject_prefix="VPN issue"):
    async with async_session_maker() as db:
        rows = []
        for i in range(count):
            t = Ticket(tenant_id=tenant["tenant_id"], submitted_by=tenant["customer_id"], department_id=tenant["department_id"],
                       subject=f"{subject_prefix} #{i}", description="The corporate VPN client disconnects repeatedly on Windows 11.",
                       status="resolved_by_ai", priority="medium", sentiment="neutral", final_response="Resolved for the purposes of this test.")
            db.add(t)
            rows.append(t)
        await db.commit()
        for t in rows:
            await db.refresh(t)
        return rows


async def teardown_tenant(tenant_id):
    async with async_session_maker() as db:
        t = str(tenant_id)
        await db.execute(text("DELETE FROM recommendation_actions WHERE recommendation_id IN (SELECT id FROM prevention_recommendations WHERE tenant_id=:t)"), {"t": t})
        await db.execute(text("DELETE FROM recommendation_evidence WHERE recommendation_id IN (SELECT id FROM prevention_recommendations WHERE tenant_id=:t)"), {"t": t})
        await db.execute(text("DELETE FROM prevention_recommendations WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM knowledge_articles WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM incidents WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM audit_logs WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM tickets WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM users WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM departments WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM organizations WHERE id=:t"), {"t": t})
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_repeated_category_creates_a_recommendation_with_the_correct_supporting_count():
    tenant = await make_tenant()
    try:
        await make_tickets(tenant, MIN_REPEATED_CATEGORY_TICKETS)
        async with async_session_maker() as db:
            created = await generate_recommendations(db, tenant["tenant_id"])
            await db.commit()
        rec = next((r for r in created if r.recommendation_type == "create_knowledge_article" and r.department_id == tenant["department_id"]), None)
        assert rec is not None, "a repeated category at the threshold must produce a recommendation"
        assert rec.supporting_ticket_count == MIN_REPEATED_CATEGORY_TICKETS
        assert rec.evidence_strength in ("low", "medium", "high")
        assert rec.category == "vpn"

        async with async_session_maker() as db:
            evidence = (await db.scalars(select(RecommendationEvidence).where(RecommendationEvidence.recommendation_id == rec.id))).all()
            assert len(evidence) == MIN_REPEATED_CATEGORY_TICKETS
            for row in evidence:
                assert row.reference_id is not None
                # No free-text ticket content (subject/description) leaks into aggregated evidence.
                assert "subject" not in row.detail and "description" not in row.detail
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_below_threshold_produces_no_recommendation():
    tenant = await make_tenant()
    try:
        await make_tickets(tenant, MIN_REPEATED_CATEGORY_TICKETS - 1)
        async with async_session_maker() as db:
            created = await generate_recommendations(db, tenant["tenant_id"])
        assert not any(r.recommendation_type == "create_knowledge_article" and r.department_id == tenant["department_id"] for r in created), \
            "insufficient evidence must never produce a recommendation"
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_rerunning_detection_does_not_duplicate_an_open_recommendation():
    tenant = await make_tenant()
    try:
        await make_tickets(tenant, MIN_REPEATED_CATEGORY_TICKETS)
        async with async_session_maker() as db:
            first = await generate_recommendations(db, tenant["tenant_id"])
            await db.commit()
            second = await generate_recommendations(db, tenant["tenant_id"])
            await db.commit()
        assert len([r for r in first if r.department_id == tenant["department_id"]]) == 1
        assert len([r for r in second if r.department_id == tenant["department_id"]]) == 0, "a still-open recommendation must not be duplicated by a second scan"
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_recommendations_are_tenant_isolated():
    tenant_a = await make_tenant()
    tenant_b = await make_tenant()
    try:
        await make_tickets(tenant_a, MIN_REPEATED_CATEGORY_TICKETS)
        async with async_session_maker() as db:
            created_b = await generate_recommendations(db, tenant_b["tenant_id"])
        assert created_b == [], "tenant B must never see tenant A's ticket evidence"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_a_token = create_access_token(tenant_a["admin_id"], "system_admin", None, tenant_a["tenant_id"])
            admin_b_token = create_access_token(tenant_b["admin_id"], "system_admin", None, tenant_b["tenant_id"])
            await client.post("/api/prevention/scan", headers=auth(admin_a_token))
            listed_b = await client.get("/api/prevention/recommendations", headers=auth(admin_b_token))
            assert listed_b.status_code == 200
            assert listed_b.json() == []
    finally:
        await teardown_tenant(tenant_a["tenant_id"])
        await teardown_tenant(tenant_b["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_customer_cannot_scan_or_review_recommendations():
    tenant = await make_tenant()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            customer_token = create_access_token(tenant["customer_id"], "customer", None, tenant["tenant_id"])
            denied_scan = await client.post("/api/prevention/scan", headers=auth(customer_token))
            assert denied_scan.status_code == 403
            denied_list = await client.get("/api/prevention/recommendations", headers=auth(customer_token))
            assert denied_list.status_code == 403
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_convert_to_knowledge_creates_a_pending_review_article_and_links_it():
    tenant = await make_tenant()
    try:
        await make_tickets(tenant, MIN_REPEATED_CATEGORY_TICKETS)
        async with async_session_maker() as db:
            created = await generate_recommendations(db, tenant["tenant_id"])
            await db.commit()
        rec = next(r for r in created if r.department_id == tenant["department_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            converted = await client.post(f"/api/prevention/recommendations/{rec.id}/convert-to-knowledge", headers=auth(admin_token))
            assert converted.status_code == 201, converted.text
            assert converted.json()["recommendation"]["status"] == "converted"
            article_id = converted.json()["knowledge_article_id"]

        async with async_session_maker() as db:
            article = await db.get(KnowledgeArticle, article_id)
            assert article is not None and article.status == "pending_review"
            assert article.source_signal == "predictive_prevention"
            refreshed = await db.get(PreventionRecommendation, rec.id)
            assert str(refreshed.linked_knowledge_article_id) == str(article_id)
            action = await db.scalar(select(RecommendationAction).where(RecommendationAction.recommendation_id == rec.id, RecommendationAction.action_type == "convert_to_knowledge"))
            assert action is not None
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_dismiss_records_reason_and_action_history():
    tenant = await make_tenant()
    try:
        await make_tickets(tenant, MIN_REPEATED_CATEGORY_TICKETS)
        async with async_session_maker() as db:
            created = await generate_recommendations(db, tenant["tenant_id"])
            await db.commit()
        rec = next(r for r in created if r.department_id == tenant["department_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            dismissed = await client.post(f"/api/prevention/recommendations/{rec.id}/dismiss", headers=auth(admin_token), json={"reason": "Already covered by an existing article"})
            assert dismissed.status_code == 200, dismissed.text
            assert dismissed.json()["status"] == "dismissed"
            assert dismissed.json()["decision_reason"] == "Already covered by an existing article"

            detail = await client.get(f"/api/prevention/recommendations/{rec.id}", headers=auth(admin_token))
            assert detail.status_code == 200
            assert any(a["action_type"] == "dismiss" and a["reason"] == "Already covered by an existing article" for a in detail.json()["actions"])
    finally:
        await teardown_tenant(tenant["tenant_id"])


@pytest.mark.asyncio(loop_scope="session")
async def test_link_incident_associates_the_recommendation():
    tenant = await make_tenant()
    try:
        await make_tickets(tenant, MIN_REPEATED_CATEGORY_TICKETS)
        from app.models.platform import Incident
        async with async_session_maker() as db:
            incident = Incident(tenant_id=tenant["tenant_id"], department_id=tenant["department_id"], category="vpn",
                                 title="VPN incident", service="Networking", status="investigating", severity="high", ticket_count=5, growth_rate=0)
            db.add(incident)
            created = await generate_recommendations(db, tenant["tenant_id"])
            await db.commit()
            await db.refresh(incident)
        rec = next(r for r in created if r.recommendation_type == "create_knowledge_article" and r.department_id == tenant["department_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = create_access_token(tenant["admin_id"], "system_admin", None, tenant["tenant_id"])
            linked = await client.post(f"/api/prevention/recommendations/{rec.id}/link-incident", headers=auth(admin_token), json={"incident_id": str(incident.id)})
            assert linked.status_code == 200, linked.text
            assert linked.json()["linked_incident_id"] == str(incident.id)
    finally:
        await teardown_tenant(tenant["tenant_id"])
