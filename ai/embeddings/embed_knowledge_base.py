"""Chunks every knowledge_base article, embeds each chunk with sentence-transformers,
and inserts the vectors into the embeddings table for pgvector similarity search.

Requires the `embeddings` extra and a database with knowledge_base rows already loaded
(db/seed/load_knowledge_base.py must have run first).

Usage (from backend/):
    uv sync --extra ai
    uv run python ../ai/embeddings/embed_knowledge_base.py [--reset]
"""

import argparse
import asyncio
import os
import re
from pathlib import Path

import asyncpg
from dotenv import dotenv_values
from pgvector.asyncpg import register_vector
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]

# Target chunk size. Our current KB articles run ~150-250 words each, so most produce
# a single chunk — this still needs to handle longer articles correctly as the KB grows.
TARGET_WORDS_PER_CHUNK = 250


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


def chunk_text(text: str, target_words: int = TARGET_WORDS_PER_CHUNK) -> list[str]:
    """Groups markdown paragraphs into chunks up to ~target_words, never splitting a
    paragraph across chunks."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for para in paragraphs:
        para_words = len(para.split())
        if current and current_words + para_words > target_words:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0
        current.append(para)
        current_words += para_words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="Delete all existing embeddings first"
    )
    args = parser.parse_args()

    env = dotenv_values(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set — copy .env.example to .env first.")
    model_name = os.environ.get("EMBEDDING_MODEL") or env.get(
        "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )

    conn = await asyncpg.connect(_asyncpg_url(database_url))
    await register_vector(conn)

    try:
        existing = await conn.fetchval("SELECT count(*) FROM embeddings")
        if existing and not args.reset:
            print(
                f"{existing} embeddings already present, skipping "
                "(pass --reset to re-embed from scratch)."
            )
            return

        articles = await conn.fetch(
            """
            SELECT k.id, k.title, k.content, d.name AS department
            FROM knowledge_base k
            JOIN departments d ON d.id = k.department_id
            WHERE k.tenant_id IS NOT NULL
              AND k.status = 'approved'
              AND k.version = '1.0'
              AND k.is_publishable = true
              AND length(trim(k.content)) > 0
            ORDER BY d.name, k.title
            """
        )
        if not articles:
            raise SystemExit(
                "No knowledge_base rows found. Run db/seed/load_knowledge_base.py first."
            )
        print(f"Loading embedding model {model_name}...")
        model = SentenceTransformer(model_name)

        rows_to_insert: list[tuple] = []
        for article in articles:
            chunks = chunk_text(article["content"])
            vectors = model.encode(chunks, show_progress_bar=False)
            for chunk_index, (chunk, vector) in enumerate(zip(chunks, vectors)):
                rows_to_insert.append(
                    (article["id"], chunk_index, chunk, vector.tolist())
                )
        print(
            f"Chunked {len(articles)} articles into {len(rows_to_insert)} chunks "
            f"(model dim {len(rows_to_insert[0][3])})."
        )

        async with conn.transaction():
            if existing:
                await conn.execute("DELETE FROM embeddings")
                print(f"--reset: removed {existing} existing embeddings.")

            await conn.executemany(
                """
                INSERT INTO embeddings (knowledge_base_id, chunk_index, chunk_text, embedding)
                VALUES ($1, $2, $3, $4)
                """,
                rows_to_insert,
            )

        totals = await conn.fetchrow(
            "SELECT count(*) AS total, count(embedding) AS non_null FROM embeddings"
        )
        print(
            f"Inserted {len(rows_to_insert)} embeddings. "
            f"SELECT count(*) = {totals['total']}; non-null vectors = {totals['non_null']}."
        )

        by_dept = await conn.fetch(
            """
            SELECT d.name, count(*) FROM embeddings e
            JOIN knowledge_base k ON k.id = e.knowledge_base_id
            JOIN departments d ON d.id = k.department_id
            GROUP BY d.name ORDER BY d.name
            """
        )
        for row in by_dept:
            print(f"  {row['name']}: {row['count']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
