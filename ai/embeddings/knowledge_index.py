"""Publishes an Admin-approved KnowledgeArticle into the retrieval corpus.

Mirrors ``resolution_index.py``'s pattern in spirit (only ever called after an
explicit human approval, never automatically) but NOT in its best-effort/
silent-failure behavior: the product contract here is that an approved
article is genuinely retrievable, so embedding is a required step, not an
optional add-on. If it fails, ``EmbeddingGenerationError`` propagates and the
caller (routers/platform.py:approve_article) never commits — the
KnowledgeBaseDocument row this function adds is rolled back along with it,
so a failed publish never leaves a half-published, unsearchable article
behind. See EmbeddingGenerationError's docstring for why this was previously
swallowed and why that was wrong.
"""
import asyncio
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

_model = None
_model_lock = asyncio.Lock()


class EmbeddingGenerationError(RuntimeError):
    """Raised when the embedding model fails to load or encode the article
    text (missing optional ai/rag extra, model load error, or a timeout).
    Previously this was caught and logged at INFO level, leaving the article
    marked "published" with a KnowledgeBaseDocument row that had no Embedding
    row — genuinely unsearchable despite reporting success. Publication must
    fail clearly instead so an Admin can retry rather than unknowingly
    trusting a citation source that can never actually be retrieved."""


def _load_model():
    from dotenv import dotenv_values
    from sentence_transformers import SentenceTransformer
    root = Path(__file__).resolve().parents[2]
    env = dotenv_values(root / ".env")
    name = os.environ.get("EMBEDDING_MODEL") or env.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    return SentenceTransformer(name)


async def _get_model():
    global _model
    # Guards against two concurrent callers both cold-loading the model (each
    # a multi-second, CPU-heavy operation) the first time this process embeds
    # anything — without this, concurrent requests could each independently
    # exceed the per-call timeout below while duplicating the load.
    async with _model_lock:
        if _model is None:
            _model = await asyncio.to_thread(_load_model)
        return _model


async def publish_knowledge_article(db: AsyncSession, article, timeout_seconds: float = 60) -> "KnowledgeBaseDocument":
    """Creates the retrieval-corpus row for an approved article, embeds it, and
    returns it. Caller is responsible for the surrounding transaction
    (commit/refresh) and for setting ``article.published_knowledge_base_id``
    on the result. Raises EmbeddingGenerationError if embedding fails —
    the caller must not commit in that case.
    """
    from app.models.knowledge_base import KnowledgeBaseDocument
    document = KnowledgeBaseDocument(
        tenant_id=article.tenant_id, department_id=article.department_id, title=article.title,
        content=article.body, status="approved", version=article.version, is_publishable=True,
    )
    db.add(document)
    await db.flush()
    try:
        model = await asyncio.wait_for(_get_model(), timeout=timeout_seconds)
        vector = await asyncio.wait_for(asyncio.to_thread(lambda: model.encode(article.body).tolist()), timeout=timeout_seconds)
    except Exception as exc:
        raise EmbeddingGenerationError(f"Failed to embed knowledge article {article.id}: {type(exc).__name__}") from exc
    from app.models.embedding import Embedding
    db.add(Embedding(knowledge_base_id=document.id, chunk_index=0, chunk_text=article.body, embedding=vector))
    return document
