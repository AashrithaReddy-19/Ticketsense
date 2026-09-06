"""Loads the same deterministic department/priority/sentiment classifier
artifacts the live ticket pipeline uses (``ai/graph/nodes.py``'s
``_get_classifiers``), for offline evaluation runs against the dataset
registry. Kept separate from the live pipeline's loader/cache so an
evaluation run can never share mutable state with request-serving code.
"""
import asyncio
import platform
from hashlib import sha256
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).resolve().parents[4] / "ai" / "models" / "artifacts"
TARGETS = ("department", "priority", "sentiment")

_cache: dict[str, object] = {}


class ClassifierArtifactUnavailable(RuntimeError):
    """Raised when the requested target's trained artifact does not exist on
    disk. Evaluation runs must fail closed with an honest status rather than
    fabricating predictions."""


def artifact_path(target: str) -> Path:
    return ARTIFACTS_DIR / f"{target}_classifier.joblib"


def _load(target: str):
    import joblib
    path = artifact_path(target)
    if not path.exists():
        raise ClassifierArtifactUnavailable(f"No trained artifact for target '{target}' at {path}")
    return joblib.load(path)


async def get_classifier(target: str):
    if target not in TARGETS:
        raise ValueError(f"Unknown evaluation target: {target}")
    if target not in _cache:
        _cache[target] = await asyncio.to_thread(_load, target)
    return _cache[target]


def artifact_content_hash(target: str) -> str | None:
    path = artifact_path(target)
    if not path.exists():
        return None
    return sha256(path.read_bytes()).hexdigest()


async def predict(target: str, texts: list[str]) -> tuple[list[str], list[list[float]] | None, list[str] | None]:
    """Returns (predicted_labels, predicted_probabilities_or_None, proba_class_order_or_None)."""
    pipeline = await get_classifier(target)

    def _run():
        predictions = [str(label) for label in pipeline.predict(texts)]
        if hasattr(pipeline, "predict_proba"):
            probabilities = pipeline.predict_proba(texts).tolist()
            classes = [str(c) for c in pipeline.classes_]
            return predictions, probabilities, classes
        return predictions, None, None

    return await asyncio.to_thread(_run)


def environment_info() -> dict:
    import sklearn
    return {"python_version": platform.python_version(), "platform": platform.platform(), "sklearn_version": sklearn.__version__}


def git_commit() -> str | None:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ARTIFACTS_DIR.parents[2]),
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or None if result.returncode == 0 else None
    except Exception:
        return None
