"""Verifies the Phase 13 controlled retraining workflow's registry: a trained
candidate never becomes active on its own, promotion is comparison-gated (or
forceable), and rollback restores the previously active version — all without
touching the real repo's artifacts (every path is redirected into tmp_path)."""
from pathlib import Path

import pytest

from ai.models import confidence_registry as registry
from ai.models.confidence_model import FEATURE_SCHEMA, predict_confidence


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(registry, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(registry, "VERSIONS_DIR", tmp_path / "confidence_versions")
    monkeypatch.setattr(registry, "ACTIVE_POINTER", tmp_path / "confidence_active.json")
    monkeypatch.setattr(registry, "PROMOTION_LOG", tmp_path / "confidence_promotion_log.jsonl")
    yield


def _candidate(version: str, roc_auc: float):
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    pipeline = Pipeline([("model", LogisticRegression())])
    pipeline.fit([[0.0] * len(FEATURE_SCHEMA), [1.0] * len(FEATURE_SCHEMA)], [0, 1])
    return {"pipeline": pipeline, "feature_schema": FEATURE_SCHEMA, "model_version": version, "trained_at": "t", "metrics": {"roc_auc": roc_auc}}


def test_saving_a_candidate_never_makes_it_active():
    registry.save_candidate("v1", _candidate("v1", 0.7))
    assert registry.load_active_metadata() is None
    assert registry.active_artifact_path() is None


def test_promote_makes_a_specific_version_active_and_is_logged():
    registry.save_candidate("v1", _candidate("v1", 0.7))
    registry.promote("v1", note="first deploy")
    assert registry.load_active_metadata()["version"] == "v1"
    assert registry.PROMOTION_LOG.exists()


def test_promote_refuses_a_version_that_was_never_trained():
    with pytest.raises(FileNotFoundError):
        registry.promote("does-not-exist")


def test_compare_to_active_reports_improvement_when_no_active_model_exists():
    result = registry.compare_to_active({"roc_auc": 0.6})
    assert result["active_version"] is None and result["improved_or_first"] is True


def test_compare_to_active_flags_a_regression():
    registry.save_candidate("v1", _candidate("v1", 0.9))
    registry.promote("v1")
    result = registry.compare_to_active({"roc_auc": 0.5})
    assert result["active_value"] == 0.9 and result["improved_or_first"] is False


def test_rollback_restores_the_previously_active_version():
    registry.save_candidate("v1", _candidate("v1", 0.7))
    registry.save_candidate("v2", _candidate("v2", 0.8))
    registry.promote("v1")
    registry.promote("v2")
    assert registry.load_active_metadata()["version"] == "v2"
    restored = registry.rollback()
    assert restored == "v1"
    assert registry.load_active_metadata()["version"] == "v1"


def test_rollback_with_no_prior_version_returns_none():
    registry.save_candidate("v1", _candidate("v1", 0.7))
    registry.promote("v1")
    assert registry.rollback() is None


def test_predict_confidence_uses_the_promoted_version_without_an_explicit_path(monkeypatch):
    registry.save_candidate("v1", _candidate("v1", 0.7))
    registry.promote("v1")
    score, version, trained = predict_confidence({name: 0.5 for name in FEATURE_SCHEMA})
    assert trained is True and version == "v1" and 0 <= score <= 1
