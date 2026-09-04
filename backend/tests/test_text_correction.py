"""Verifies the hybrid corrector's core safety property — technical tokens (error
codes, IPs, URLs, file paths, versions, ticket IDs) survive correction byte-for-byte —
and that the evaluation CLI's harness runs end-to-end without a real dataset present
(it must refuse to print a comparison table, not fabricate one)."""
import json
import subprocess
import sys
from pathlib import Path

from ai.evaluation.text_correction import hybrid_correct, mask_technical_tokens, restore_technical_tokens, rule_based_correct


def test_rule_based_correction_collapses_whitespace_and_fixes_punctuation_spacing():
    assert rule_based_correct("click  reconnect ,then retry") == "click reconnect, then retry"


def test_masking_and_restoring_a_technical_token_is_lossless():
    text = "Connect to 10.0.0.5 and check ERR-4042 in v2.3.1"
    masked, restore = mask_technical_tokens(text)
    assert "10.0.0.5" not in masked and "ERR-4042" not in masked
    assert restore_technical_tokens(masked, restore) == text


def test_hybrid_correction_preserves_every_technical_token_while_cleaning_prose():
    corrupted = "cl1ck  reconnect  ,then check ERR-4042 at 10.0.0.5 per v2.3.1 docs https://kb.example.com/TKT-9001"
    corrected = hybrid_correct(corrupted, underlying="rule_based")
    for token in ("ERR-4042", "10.0.0.5", "v2.3.1", "https://kb.example.com/TKT-9001", "TKT-9001"):
        assert token in corrected
    assert "  " not in corrected  # rule-based whitespace cleanup still ran on the prose


def test_evaluation_cli_refuses_to_fabricate_results_without_a_dataset(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(repo_root / "ai" / "evaluation" / "text_correction_eval.py")],
        capture_output=True, text=True, cwd=repo_root, env={"PYTHONPATH": str(repo_root)},
    )
    assert "Refusing to print a fabricated comparison" in result.stdout


def test_evaluation_cli_reports_real_metrics_on_a_small_labelled_fixture(tmp_path):
    """Smoke-tests the harness end-to-end on a tiny fixture authored for this test —
    not a claim about real-world OCR-correction accuracy."""
    dataset = tmp_path / "pairs.jsonl"
    dataset.write_text("\n".join(json.dumps(row) for row in [
        {"corrupted": "cl1ck  reconnect ,retry ERR-4042", "correct": "Click reconnect, retry ERR-4042"},
        {"corrupted": "res3t  the  password", "correct": "Reset the password"},
    ]), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(repo_root / "ai" / "evaluation" / "text_correction_eval.py"), "--dataset", str(dataset), "--methods", "rule_based"],
        capture_output=True, text=True, cwd=repo_root, env={"PYTHONPATH": str(repo_root)},
    )
    assert "Number of samples evaluated: 2" in result.stdout
    assert "Mean CER before -> after" in result.stdout
