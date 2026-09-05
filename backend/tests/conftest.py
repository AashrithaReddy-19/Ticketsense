"""Shared pytest fixtures.

Several tests need a real, end-to-end HTTP flow against the actual seeded demo
tenant (its knowledge base, embeddings, and seeded engineers) rather than a
synthetic isolated tenant, because they're specifically proving the real
retrieval/grounding pipeline or the real seeded engineer roster works. Every
ticket such a test creates against the shared demo tenant must be deleted
again so repeated CI/local runs never accumulate tickets in the demo dataset
a human reviewer or a live demo session might also be looking at.

Use the ``demo_tickets`` fixture: append each created ticket's id (str or
UUID) to the list it yields, and its rows (and everything that cascades from
ticket_id — drafts, events, decisions, messages, etc., all confirmed
ON DELETE CASCADE) are deleted after the test, pass or fail.
"""
import pytest_asyncio
from sqlalchemy import text

from app.database import async_session_maker


@pytest_asyncio.fixture
async def demo_users():
    """Same idea as ``demo_tickets`` for a test that self-registers a throwaway
    customer account against the shared demo tenant (e.g. to prove per-owner
    authorization) rather than creating one directly in an isolated tenant."""
    created: list[str] = []
    yield created
    if created:
        ids = [str(i) for i in created]
        async with async_session_maker() as db:
            await db.execute(text("DELETE FROM audit_logs WHERE user_id = ANY(:ids)"), {"ids": ids})
            await db.execute(text("DELETE FROM notifications WHERE user_id = ANY(:ids)"), {"ids": ids})
            await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})
            await db.commit()


@pytest_asyncio.fixture
async def demo_playbooks():
    """Same idea as ``demo_tickets``, for a test that creates real playbook rows
    (and their applications) against the shared demo tenant."""
    created: list[str] = []
    yield created
    if created:
        ids = [str(i) for i in created]
        async with async_session_maker() as db:
            await db.execute(text("DELETE FROM playbook_applications WHERE playbook_id = ANY(:ids)"), {"ids": ids})
            await db.execute(text("DELETE FROM playbooks WHERE id = ANY(:ids)"), {"ids": ids})
            await db.commit()


@pytest_asyncio.fixture
async def demo_tickets():
    created: list[str] = []
    yield created
    if created:
        ids = [str(i) for i in created]
        async with async_session_maker() as db:
            # knowledge_articles.source_ticket_ids is a JSONB array, not a real foreign
            # key, so an auto-drafted knowledge-gap article survives a plain ticket
            # delete unless removed explicitly first.
            for ticket_id in ids:
                await db.execute(text("DELETE FROM knowledge_articles WHERE source_ticket_ids @> :id"), {"id": f'["{ticket_id}"]'})
            await db.execute(text("DELETE FROM tickets WHERE id = ANY(:ids)"), {"ids": ids})
            await db.commit()
