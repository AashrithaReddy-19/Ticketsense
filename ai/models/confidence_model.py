"""Independent confidence prediction; never uses an LLM self-assessment."""
from pathlib import Path
from typing import Mapping

import joblib

FEATURE_SCHEMA = (
    "classification_probability", "classification_margin", "retrieval_similarity",
    "retrieval_score_gap", "citation_coverage", "valid_evidence_count",
    "ocr_quality", "description_completeness", "draft_validation",
)
ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "confidence_model.joblib"


def normalized_features(raw: Mapping[str, float | int | None]) -> list[float]:
    values=[]
    for name in FEATURE_SCHEMA:
        value=raw.get(name)
        values.append(0.0 if value is None else float(value))
    return values


def fallback_confidence(raw: Mapping[str, float | int | None]) -> float:
    f=dict(zip(FEATURE_SCHEMA,normalized_features(raw)))
    evidence=min(1.0,f["valid_evidence_count"]/3)
    score=(.25*f["classification_probability"]+.10*f["classification_margin"]+.22*f["retrieval_similarity"]+.10*f["citation_coverage"]+.08*evidence+.08*f["ocr_quality"]+.09*f["description_completeness"]+.08*f["draft_validation"])
    return round(max(0.0,min(1.0,score)),4)


def predict_confidence(raw: Mapping[str, float | int | None], artifact_path: Path | None = None) -> tuple[float,str,bool]:
    """Return score, model version, and whether a trained artifact was used.

    With no explicit `artifact_path`, resolves the currently *promoted* version
    from the confidence-model registry (see confidence_registry.py) rather than a
    fixed file — so promoting or rolling back a version takes effect immediately
    without redeploying. Passing `artifact_path` explicitly (as the missing/malformed
    artifact tests do) bypasses the registry entirely, unchanged from before.
    """
    if artifact_path is None:
        from ai.models.confidence_registry import active_artifact_path
        artifact_path = active_artifact_path() or ARTIFACT_PATH
    if not artifact_path.exists(): return fallback_confidence(raw),"safe-fallback-v1",False
    try:
        artifact=joblib.load(artifact_path)
        if tuple(artifact["feature_schema"]) != FEATURE_SCHEMA: raise ValueError("feature schema mismatch")
        score=float(artifact["pipeline"].predict_proba([normalized_features(raw)])[0][1])
        return round(max(0.0,min(1.0,score)),4),str(artifact["model_version"]),True
    except Exception:
        return fallback_confidence(raw),"safe-fallback-v1",False
