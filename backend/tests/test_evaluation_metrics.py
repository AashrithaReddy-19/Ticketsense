"""Verifies the OCR/text-correction evaluation metrics against hand-computed values —
these are the only numbers in the evaluation pipeline that can be checked without a
labelled dataset, and they must be exactly right since every downstream report figure
depends on them."""
from ai.evaluation.metrics import (
    character_error_rate, error_code_accuracy, technical_token_preservation, word_error_rate,
)


def test_character_error_rate_is_zero_for_an_exact_match():
    assert character_error_rate("VPN error", "VPN error") == 0.0


def test_character_error_rate_matches_hand_computed_edit_distance():
    # "hello" -> "hallo" is a single substitution over 5 reference characters.
    assert character_error_rate("hallo", "hello") == 1 / 5


def test_character_error_rate_handles_empty_reference():
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("text", "") == 1.0


def test_word_error_rate_matches_hand_computed_edit_distance():
    # One substitution ("token" -> "ticket") over 5 reference words.
    ref = "reset the cached vpn token"
    hyp = "reset the cached vpn ticket"
    assert word_error_rate(hyp, ref) == 1 / 5


def test_technical_tokens_are_detected_and_preservation_is_measured():
    original = "Error ERR-4042 at 10.0.0.5 for v2.3.1, see https://kb.example.com/TKT-9001"
    unchanged = original
    corrupted = "Error at 10.0.0.5 for v2.3.1, see https://kb.example.com/TKT-9001"  # dropped ERR-4042
    preserved = technical_token_preservation(original, unchanged)
    dropped = technical_token_preservation(original, corrupted)
    assert preserved["error_code"] == 1.0
    assert dropped["error_code"] == 0.0
    assert dropped["ip_address"] == 1.0  # untouched category stays fully preserved


def test_error_code_accuracy_is_none_when_reference_has_no_codes():
    assert error_code_accuracy("some text", "no codes here") is None


def test_error_code_accuracy_counts_exact_matches():
    reference = "codes ERR-100 and ERR-200 were logged"
    hypothesis = "codes ERR-100 and ERR-999 were logged"
    assert error_code_accuracy(hypothesis, reference) == 0.5
