"""Publishes an Admin-approved KnowledgeArticle into the retrieval corpus.

Mirrors ``resolution_index.py``'s pattern: only ever called after an explicit
human approval (never automatically), creates the retrievable
``knowledge_base`` row unconditionally (cheap, no ML required), then makes a
best-effort attempt to embed it so it is actually reachable by vector search.
A failed embedding (missing optional ``ai``/``rag`` extra, model load error)
never blocks publication — the article is published either way, and the gap
is logged so it can be re-embedded later; it is simply not yet vector-
searchable until that happens.
"""
import asyncio
import logging
import os
from pathlib import Path

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


async def publish_knowledge_article(db: AsyncSession, article) -> "KnowledgeBaseDocument":
    """Creates the retrieval-corpus row for an approved article and returns it.

    Caller is responsible for the surrounding transaction (commit/refresh) and
    for setting ``article.published_knowledge_base_id`` on the result.
    """
    from app.models.knowledge_base import KnowledgeBaseDocument
    document = KnowledgeBaseDocument(
        tenant_id=article.tenant_id, department_id=article.department_id, title=article.title,
        content=article.body, status="approved", version=article.version, is_publishable=True,
    )
    db.add(document)
    await db.flush()
    try:
        vector = await asyncio.wait_for(asyncio.to_thread(lambda: _get_model().encode(article.body).tolist()), timeout=30)
        from app.models.embedding import Embedding
        db.add(Embedding(knowledge_base_id=document.id, chunk_index=0, chunk_text=article.body, embedding=vector))
    except Exception:
        logger.info("Embedding unavailable for published knowledge article %s; document is stored but not yet vector-searchable", document.id)
    return document
