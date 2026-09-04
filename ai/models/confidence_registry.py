"""Versioned storage, comparison, and controlled promotion/rollback for the
independent confidence model (Phase 13).

Training a new candidate (train_confidence.py) never replaces the model the live
API is using — every candidate is written to its own versioned file under
artifacts/confidence_versions/. A separate `promote()` call, gated behind an
explicit CLI flag and a metric-improvement check, updates the small `active`
pointer the live API reads. Every promotion is appended to a log, so `rollback()`
can restore the previous active version without retraining anything.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
VERSIONS_DIR = ARTIFACTS_DIR / "confidence_versions"
ACTIVE_POINTER = ARTIFACTS_DIR / "confidence_active.json"
PROMOTION_LOG = ARTIFACTS_DIR / "confidence_promotion_log.jsonl"


def version_path(version: str) -> Path:
    return VERSIONS_DIR / f"{version}.joblib"


def save_candidate(version: str, payload: dict) -> Path:
    import joblib
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = version_path(version)
    joblib.dump(payload, path)
    return path


def load_active_metadata() -> dict | None:
    if not ACTIVE_POINTER.exists(): return None
    try: return json.loads(ACTIVE_POINTER.read_text(encoding="utf-8"))
    except Exception: return None


def active_artifact_path() -> Path | None:
    meta = load_active_metadata()
    if not meta or "version" not in meta: return None
    path = version_path(meta["version"])
    return path if path.exists() else None


def _append_log(event: str, version: str, note: str = "") -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    with PROMOTION_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": event, "version": version, "note": note, "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")


def promote(version: str, note: str = "") -> None:
    """Makes `version` the one the live API loads. Raises if it was never trained."""
    if not version_path(version).exists():
        raise FileNotFoundError(f"No trained candidate for version {version!r}; train it first.")
    previous = load_active_metadata()
    ACTIVE_POINTER.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_POINTER.write_text(json.dumps({
        "version": version, "promoted_at": datetime.now(timezone.utc).isoformat(),
        "previous_version": previous.get("version") if previous else None,
    }), encoding="utf-8")
    _append_log("promote", version, note)


def rollback() -> str | None:
    """Restores the previously active version. Returns its name, or None if there
    is no earlier version to roll back to."""
    current = load_active_metadata()
    target = (current or {}).get("previous_version")
    if not target: return None
    promote(target, note="rollback")
    return target


def list_versions() -> list[dict]:
    import joblib
    if not VERSIONS_DIR.exists(): return []
    out = []
    for path in sorted(VERSIONS_DIR.glob("*.joblib")):
        try:
            payload = joblib.load(path)
            out.append({"version": payload.get("model_version", path.stem), "trained_at": payload.get("trained_at"), "metrics": payload.get("metrics", {})})
        except Exception:
            continue
    return out


def compare_to_active(candidate_metrics: dict, metric: str = "roc_auc") -> dict:
    """Compares a freshly trained candidate to the currently active model on one
    headline metric. Returns enough for a human (or --deploy gate) to decide."""
    active_meta = load_active_metadata()
    active_metrics = None
    if active_meta:
        path = version_path(active_meta["version"])
        if path.exists():
            import joblib
            active_metrics = joblib.load(path).get("metrics")
    active_value = (active_metrics or {}).get(metric)
    candidate_value = candidate_metrics.get(metric)
    improved = active_value is None or (candidate_value is not None and candidate_value >= active_value)
    return {
        "metric": metric, "active_version": active_meta.get("version") if active_meta else None,
        "active_value": active_value, "candidate_value": candidate_value, "improved_or_first": improved,
    }
