"""Section 16: knowledge-gap detection and the draft -> Admin-approved -> published,
embedded retrieval-corpus lifecycle."""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import async_session_maker
from app.main import app
from app.models.embedding import Embedding
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import KnowledgeArticle


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_approving_an_article_publishes_a_real_embedded_retrievable_document():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        manager = await token(client, "kbmanager@demo.com")
        customer = await token(client, "customer@demo.com")
        unique = uuid4().hex
        generated = await client.post("/api/knowledge/articles/generate", headers=auth(manager), json={
            "title": f"Knowledge lifecycle test article {unique}",
            "body": "When the corporate VPN client fails with a timeout, clear its cached session and reconnect using the latest client version.",
        })
        assert generated.status_code == 200, generated.text
        article_id = generated.json()["id"]
        assert generated.json()["status"] == "pending_review"

        listed = await client.get("/api/knowledge/articles?status_filter=pending_review", headers=auth(manager))
        assert listed.status_code == 200
        assert any(row["id"] == article_id for row in listed.json())

        denied = await client.post(f"/api/knowledge/articles/{article_id}/approve", headers=auth(customer))
        assert denied.status_code == 403

        approved = await client.post(f"/api/knowledge/articles/{article_id}/approve", headers=auth(manager))
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "published"
        kb_id = approved.json()["knowledge_base_id"]
        assert kb_id

        again = await client.post(f"/api/knowledge/articles/{article_id}/approve", headers=auth(manager))
        assert again.status_code == 409

        searchable = await client.get("/api/knowledge", headers=auth(manager), params={"q": f"lifecycle test article {unique}"})
        assert searchable.status_code == 200
        assert any(row["id"] == kb_id for row in searchable.json())

        async with async_session_maker() as db:
            document = await db.get(KnowledgeBaseDocument, kb_id)
            assert document is not None
            assert document.status == "approved" and document.is_publishable is True
            embedding = await db.scalar(select(Embedding).where(Embedding.knowledge_base_id == kb_id))
            assert embedding is not None, "publishing an article must actually embed it, not just create the row"
            assert len(embedding.embedding) > 0


@pytest.mark.asyncio(loop_scope="session")
async def test_rejecting_an_article_records_a_reason_and_never_publishes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        manager = await token(client, "kbmanager@demo.com")
        unique = uuid4().hex
        generated = await client.post("/api/knowledge/articles/generate", headers=auth(manager), json={
            "title": f"Rejected article {unique}", "body": "This draft should never reach the retrieval corpus.",
        })
        article_id = generated.json()["id"]
        rejected = await client.post(f"/api/knowledge/articles/{article_id}/reject", headers=auth(manager), json={"reason": "Duplicate of an existing approved article"})
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

        listed = await client.get("/api/knowledge/articles?status_filter=rejected", headers=auth(manager))
        row = next(item for item in listed.json() if item["id"] == article_id)
        assert row["rejected_reason"] == "Duplicate of an existing approved article"
        assert row["published_knowledge_base_id"] is None


@pytest.mark.asyncio(loop_scope="session")
async def test_human_resolution_without_any_citation_drafts_a_knowledge_gap_article():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await token(client, "customer@demo.com")
        engineer = await token(client, "agent@demo.com")
        reviewer = await token(client, "reviewer@demo.com")
        team_lead = await token(client, "teamlead@demo.com")
        engineer_profile = await client.get("/api/auth/me", headers=auth(engineer))

        unique = uuid4().hex
        created = await client.post("/api/tickets", headers=auth(customer), json={
            "subject": f"Knowledge gap check {unique}", "description": "The corporate VPN rejects a valid password from a new laptop.",
        })
        ticket_id = created.json()["id"]
        await client.post(f"/api/tickets/{ticket_id}/assign", headers=auth(team_lead), json={"engineer_id": engineer_profile.json()["id"], "comment": "Assigning for knowledge-gap test"})
        await client.post(f"/api/tickets/{ticket_id}/start-work", headers=auth(engineer), json={"comment": "Investigating"})
        draft = await client.post(f"/api/tickets/{ticket_id}/drafts", headers=auth(engineer), json={"content": "Re-issued a new hardware token for the laptop and confirmed VPN access.", "citations": []})
        assert draft.status_code == 201, draft.text
        assert draft.json()["citations"] == []
        await client.post(f"/api/tickets/{ticket_id}/submit-for-review", headers=auth(engineer), json={"comment": "Ready"})
        approved = await client.post(f"/api/tickets/{ticket_id}/review", headers=auth(reviewer), json={"action": "approve", "review_comment": "Confirmed with the customer"})
        assert approved.status_code == 200, approved.text

        async with async_session_maker() as db:
            article = await db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.source_ticket_ids.contains([ticket_id])))
            assert article is not None, "a citation-less human resolution should draft a knowledge-gap article"
            assert article.status == "pending_review"
            assert article.source_signal == "no_cited_evidence_at_resolution"
            assert article.body == "Re-issued a new hardware token for the laptop and confirmed VPN access."


@pytest.mark.asyncio(loop_scope="session")
async def test_knowledge_gaps_and_health_endpoints_are_capability_gated_with_a_stable_shape():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        manager = await token(client, "kbmanager@demo.com")
        customer = await token(client, "customer@demo.com")

        gaps = await client.get("/api/knowledge/gaps", headers=auth(manager))
        assert gaps.status_code == 200, gaps.text
        assert set(gaps.json().keys()) == {"window_days", "weak_evidence_by_category", "heavy_edit_by_category"}
        assert gaps.json()["window_days"] == 30

        health = await client.get("/api/knowledge/health", headers=auth(manager))
        assert health.status_code == 200, health.text
        assert set(health.json().keys()) == {"stale_after_days", "articles"}
        for row in health.json()["articles"]:
            assert set(row.keys()) == {"id", "title", "department_id", "version", "age_days", "stale"}

        assert (await client.get("/api/knowledge/gaps", headers=auth(customer))).status_code == 403
        assert (await client.get("/api/knowledge/health", headers=auth(customer))).status_code == 403
