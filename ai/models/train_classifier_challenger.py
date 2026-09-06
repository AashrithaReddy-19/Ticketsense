"""Trains a genuinely different "challenger" department classifier on the
exact same labeled rows and the exact same train/test split as
train_classifier.py (same random_state=42), so a later champion-vs-
challenger comparison is a fair, real comparison of two distinct models —
not the same artifact compared against itself.

The difference is deliberate and documented, not tuned for a particular
result: unigrams only (no bigrams) and a lower vocabulary cap, a genuinely
weaker text representation than the champion's (1,2)-gram/2000-feature
TF-IDF. This is a real, reproducible variant — evaluate it (V2 Evaluation
Lab / champion-challenger comparison) before ever promoting it; nothing
here claims it is better.

Usage (from backend/):
    uv sync --extra ai
    uv run python ../ai/models/train_classifier_challenger.py
"""
import sys
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_classifier import ARTIFACTS_DIR, load_labeled_tickets  # noqa: E402

CHALLENGER_TARGET = "department"


def make_challenger_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(stop_words="english", ngram_range=(1, 1), max_features=800)),
        ("clf", LogisticRegression(max_iter=1000, C=0.5)),
    ])


def main() -> None:
    import asyncio
    from collections import Counter

    rows = asyncio.run(load_labeled_tickets())
    print(f"Loaded {len(rows)} labeled tickets.")

    # A stratified split requires at least 2 examples per class. Real demo
    # data has since grown a genuine singleton department (a single sensitive
    # payment-dispute scenario ticket) that would make the champion's own
    # training script fail identically if rerun today — this isn't specific
    # to the challenger. Drop singleton classes rather than fabricate a
    # second example, and say exactly what was dropped and why.
    counts = Counter(r["department"] for r in rows)
    singleton_departments = {dept for dept, count in counts.items() if count < 2}
    if singleton_departments:
        dropped = [r for r in rows if r["department"] in singleton_departments]
        print(f"Dropping {len(dropped)} row(s) from department(s) with fewer than 2 examples (cannot be stratified): {sorted(singleton_departments)}")
        rows = [r for r in rows if r["department"] not in singleton_departments]

    texts = [f"{r['subject']}\n{r['description']}" for r in rows]
    departments = [r["department"] for r in rows]
    indices = list(range(len(rows)))
    train_idx, test_idx = train_test_split(indices, test_size=0.2, random_state=42, stratify=departments)

    labels = [r[CHALLENGER_TARGET] for r in rows]
    X_train = [texts[i] for i in train_idx]
    X_test = [texts[i] for i in test_idx]
    y_train = [labels[i] for i in train_idx]
    y_test = [labels[i] for i in test_idx]

    pipeline = make_challenger_pipeline()
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    print(f"\n=== {CHALLENGER_TARGET} (challenger) ===")
    print(f"accuracy: {accuracy_score(y_test, y_pred):.3f}")
    print(classification_report(y_test, y_pred, zero_division=0))

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    artifact_path = ARTIFACTS_DIR / f"{CHALLENGER_TARGET}_classifier_challenger.joblib"
    joblib.dump(pipeline, artifact_path)
    print(f"saved: {artifact_path}")


if __name__ == "__main__":
    main()
