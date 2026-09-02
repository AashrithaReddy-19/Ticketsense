"""Trains the department/priority/sentiment ticket classifier on the labeled rows in
`tickets` (currently: data/synthetic_labeled_tickets.py's ~96-row set) and saves the
fitted pipelines to ai/models/artifacts/ for the LangGraph classify node to load.

Three independent scikit-learn pipelines (TfidfVectorizer + LogisticRegression), one
per target — the targets have unrelated label spaces, so independent pipelines are
simpler to reason about and evaluate than one multi-output model. This is still "the
classifier" (one of the project's 2 allowed models), distinct from the separate
confidence/escalation model.

~96 rows is small — this proves the pipeline end-to-end, it isn't a tuned model.

Usage (from backend/):
    uv sync --extra ai
    uv run python ../ai/models/train_classifier.py
"""

import asyncio
import os
import re
from pathlib import Path

import asyncpg
import joblib
from dotenv import dotenv_values
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
TARGETS = ["department", "priority", "sentiment"]


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


async def load_labeled_tickets() -> list[dict]:
    env = dotenv_values(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set — copy .env.example to .env first.")

    conn = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        rows = await conn.fetch(
            """
            SELECT t.subject, t.description, t.priority, t.sentiment, d.name AS department
            FROM tickets t
            JOIN departments d ON d.id = t.department_id
            WHERE t.department_id IS NOT NULL
              AND t.priority IS NOT NULL
              AND t.sentiment IS NOT NULL
            """
        )
    finally:
        await conn.close()

    if not rows:
        raise SystemExit(
            "No fully-labeled tickets found. Run "
            "data/synthetic_labeled_tickets.py first."
        )
    return [dict(r) for r in rows]


def make_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=2000),
            ),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    )


def main() -> None:
    rows = asyncio.run(load_labeled_tickets())
    texts = [f"{r['subject']}\n{r['description']}" for r in rows]
    print(f"Loaded {len(rows)} labeled tickets.")

    # Single split (stratified on department, the most balanced target) reused across
    # all three targets, so results are on the exact same train/test tickets.
    departments = [r["department"] for r in rows]
    indices = list(range(len(rows)))
    train_idx, test_idx = train_test_split(
        indices, test_size=0.2, random_state=42, stratify=departments
    )

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    for target in TARGETS:
        labels = [r[target] for r in rows]
        X_train = [texts[i] for i in train_idx]
        X_test = [texts[i] for i in test_idx]
        y_train = [labels[i] for i in train_idx]
        y_test = [labels[i] for i in test_idx]

        pipeline = make_pipeline()
        pipeline.fit(X_train, y_train)
        y_pred = pipeline.predict(X_test)

        print(f"\n=== {target} ===")
        print(f"accuracy: {accuracy_score(y_test, y_pred):.3f}")
        print(classification_report(y_test, y_pred, zero_division=0))

        artifact_path = ARTIFACTS_DIR / f"{target}_classifier.joblib"
        joblib.dump(pipeline, artifact_path)
        print(f"saved: {artifact_path}")


if __name__ == "__main__":
    main()
