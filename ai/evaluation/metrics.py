"""Real, dependency-free text-quality metrics shared by the OCR and text-correction
evaluation CLIs. No numbers here are simulated — every function is a standard,
independently verifiable string-distance computation over whatever ground truth is
supplied by the caller."""
from __future__ import annotations
import re


def _levenshtein(a: list, b: list) -> int:
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
        previous = current
    return previous[-1]


def character_error_rate(hypothesis: str, reference: str) -> float:
    """Edit distance over characters, normalized by reference length. 0 = exact match."""
    if not reference: return 0.0 if not hypothesis else 1.0
    return _levenshtein(list(hypothesis), list(reference)) / len(reference)


def word_error_rate(hypothesis: str, reference: str) -> float:
    """Edit distance over whitespace-tokenized words, normalized by reference word count."""
    ref_words = reference.split()
    if not ref_words: return 0.0 if not hypothesis.split() else 1.0
    return _levenshtein(hypothesis.split(), ref_words) / len(ref_words)


# Technical tokens a correction pass must never alter — matched conservatively so
# ordinary words aren't mistaken for one of these categories. Ordered so a broader
# "container" pattern (a URL or file path) is matched, and can be masked, before a
# narrower pattern that would otherwise also match a substring of it (e.g. a ticket
# ID inside a URL) — callers that mask sequentially (see text_correction.py) rely on
# this order to avoid producing nested, unrestorable placeholders.
TECHNICAL_TOKEN_PATTERNS = {
    "url": re.compile(r"\bhttps?://\S+\b"),
    "file_path": re.compile(r"(?:[A-Za-z]:\\|/)[\w./\\-]+"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "version": re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b"),
    "ticket_id": re.compile(r"\bTKT-\d+\b", re.IGNORECASE),
    # Excludes TKT-#### so a ticket ID is never double-counted as a generic error code.
    "error_code": re.compile(r"\b(?!TKT-\d)[A-Z]{2,}-\d{3,}\b"),
}


def extract_technical_tokens(text: str) -> dict[str, set[str]]:
    return {name: set(pattern.findall(text)) for name, pattern in TECHNICAL_TOKEN_PATTERNS.items()}


def technical_token_preservation(original: str, corrected: str) -> dict[str, float]:
    """Fraction of each technical-token category in `original` that survives unchanged
    in `corrected`. 1.0 = fully preserved; categories absent from `original` are omitted."""
    before = extract_technical_tokens(original)
    after = extract_technical_tokens(corrected)
    result = {}
    for category, tokens in before.items():
        if not tokens: continue
        result[category] = len(tokens & after.get(category, set())) / len(tokens)
    return result


def error_code_accuracy(hypothesis: str, reference: str) -> float | None:
    """Exact-match rate of error-code tokens between hypothesis and reference text.
    Returns None (not zero) when the reference contains no error codes, so callers can
    distinguish "no codes to check" from "all codes wrong"."""
    ref_codes = TECHNICAL_TOKEN_PATTERNS["error_code"].findall(reference)
    if not ref_codes: return None
    hyp_codes = set(TECHNICAL_TOKEN_PATTERNS["error_code"].findall(hypothesis))
    return sum(1 for code in ref_codes if code in hyp_codes) / len(ref_codes)
