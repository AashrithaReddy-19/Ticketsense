"""Indexes an approved, resolved ticket's final response as a reusable retrieval source.

Runs inline at approval time (see app.services.workflow.approve_draft) using the same
lazily-loaded sentence-transformers model the LangGraph retrieve node uses, so no
separate offline job is required to keep this index current. Only ever indexes the
already reviewer-approved, customer-safe `final_response` text — never a draft, an
internal note, or unapproved content. This is a strict best-effort: any failure,
including the optional `ai`/`rag` extra not being installed, is swallowed so ticket
approval itself never fails or blocks on embedding availability.
"""
import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_model = None


def _get_model():
    global _model
    if _model is None:
        from dotenv import dotenv_values
        from sentence_transformers import SentenceTransformer
        root = Path(__file__).resolve().parents[2]
        env = dotenv_values(root / ".env")
        name = os.environ.get("EMBEDDING_MODEL") or env.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        _model = SentenceTransformer(name)
    return _model


async def index_resolution(db: AsyncSession, ticket) -> bool:
    """Best-effort upsert of one resolution embedding row. Returns True if stored."""
    if not ticket.final_response or not ticket.department_id or not ticket.tenant_id:
        return False
    try:
        vector = await asyncio.wait_for(asyncio.to_thread(lambda: _get_model().encode(ticket.final_response).tolist()), timeout=30)
        from app.models.embedding import TicketResolutionEmbedding
        stmt = pg_insert(TicketResolutionEmbedding).values(
            tenant_id=ticket.tenant_id, department_id=ticket.department_id, ticket_id=ticket.id,
            chunk_text=ticket.final_response, embedding=vector, source_version="1.0", reusable=True,
        ).on_conflict_do_update(
            index_elements=[TicketResolutionEmbedding.ticket_id],
            set_={"chunk_text": ticket.final_response, "embedding": vector, "department_id": ticket.department_id},
        )
        await db.execute(stmt)
        return True
    except Exception:
        logger.info("Resolution embedding unavailable; skipping retrieval index for ticket %s", ticket.id)
        return False
