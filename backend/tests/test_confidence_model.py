from pathlib import Path

from ai.models.confidence_model import FEATURE_SCHEMA, predict_confidence


def test_confidence_model_uses_safe_fallback_when_artifact_is_missing(tmp_path:Path):
    score,version,trained=predict_confidence({name:.5 for name in FEATURE_SCHEMA},tmp_path/"missing.joblib")
    assert 0<=score<=1 and version=="safe-fallback-v1" and trained is False


def test_confidence_model_rejects_malformed_artifact(tmp_path:Path):
    artifact=tmp_path/"bad.joblib";artifact.write_text("not a model",encoding="utf-8")
    score,version,trained=predict_confidence({},artifact)
    assert 0<=score<=1 and version=="safe-fallback-v1" and trained is False
