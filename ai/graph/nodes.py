import os
import re
from pathlib import Path

import asyncpg
import joblib
from dotenv import dotenv_values
from pgvector.asyncpg import register_vector
from sentence_transformers import SentenceTransformer

from .state import TicketState

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "models" / "artifacts"

_env = dotenv_values(ROOT / ".env")
_MODEL_NAME = os.environ.get("EMBEDDING_MODEL") or _env.get(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
_DATABASE_URL = os.environ.get("DATABASE_URL") or _env.get("DATABASE_URL", "")

_embedding_model: SentenceTransformer | None = None
_classifiers: dict | None = None


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(_MODEL_NAME)
    return _embedding_model


def _get_classifiers() -> dict:
    global _classifiers
    if _classifiers is None:
        loaded = {}
        for target in ("department", "priority", "sentiment"):
            path = ARTIFACTS_DIR / f"{target}_classifier.joblib"
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} not found — run ai/models/train_classifier.py first."
                )
            loaded[target] = joblib.load(path)
        _classifiers = loaded
    return _classifiers


async def classify_node(state: TicketState) -> dict:
    """First real stage: predicts department/priority/sentiment from the trained
    scikit-learn pipelines (ai/models/train_classifier.py)."""
    text = f"{state['subject']}\n{state['description']}"
    classifiers = _get_classifiers()
    return {
        "department": str(classifiers["department"].predict([text])[0]),
        "priority": str(classifiers["priority"].predict([text])[0]),
        "sentiment": str(classifiers["sentiment"].predict([text])[0]),
    }


async def retrieve_node(state: TicketState, top_k: int = 3) -> dict:
    """Second real stage: embeds the ticket description and runs a department-filtered
    pgvector similarity search, using the department classify_node just predicted."""
    if not state.get("tenant_id"):
        raise ValueError("retrieve_node requires state['tenant_id']")
    if not state.get("department"):
        raise ValueError("retrieve_node requires state['department'] — run classify_node first")

    if not _DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    model = _get_embedding_model()
    vector = model.encode(state["description"]).tolist()
    article_version = state.get("article_version", "1.0")

    conn = await asyncpg.connect(_asyncpg_url(_DATABASE_URL))
    await register_vector(conn)
    try:
        rows = await conn.fetch(
            """
            SELECT k.title, k.version AS article_version, e.chunk_text,
                   e.embedding <=> $1 AS distance,
                   1 - (e.embedding <=> $1) AS similarity
            FROM embeddings e
            JOIN knowledge_base k ON k.id = e.knowledge_base_id
            JOIN departments d ON d.id = k.department_id
            WHERE k.tenant_id = $2::uuid
              AND d.name = $3
              AND k.status = 'approved'
              AND k.version = $4
              AND k.is_publishable = true
              AND length(trim(k.content)) > 0
              AND length(trim(e.chunk_text)) > 0
            ORDER BY e.embedding <=> $1
            LIMIT $5
            """,
            vector,
            state["tenant_id"],
            state["department"],
            article_version,
            top_k,
        )
    finally:
        await conn.close()

    return {
        "retrieved_chunks": [
            {
                "title": r["title"],
                "chunk_text": r["chunk_text"],
                "distance": float(r["distance"]),
                "similarity": float(r["similarity"]),
                "article_version": r["article_version"],
            }
            for r in rows
        ]
    }


async def draft_node(state: TicketState) -> dict:
    raise NotImplementedError(
        "Draft generation is a later phase — needs an LLM provider behind "
        "ai/agents/llm_interface.py wired in here."
    )


async def score_node(state: TicketState) -> dict:
    raise NotImplementedError(
        "Confidence scoring is a later phase — needs the separate confidence/"
        "escalation model (ai/models/), not the classifier trained here."
    )
