"""Corrupted-OCR-text correction methods compared by text_correction_eval.py.

Four methods, in increasing sophistication:
  - rule_based: deterministic regex fixes only (whitespace, common glyph confusions).
  - symspell: dictionary-based spelling correction (optional: pip install symspellpy).
  - transformer: a seq2seq spelling-correction model (optional: pip install transformers torch).
  - hybrid: masks technical tokens out, runs the best available underlying method on
    the remaining prose, then restores the technical tokens verbatim. This is the
    only method safe to run on ticket text that contains error codes, IPs, URLs,
    file paths, versions or ticket IDs — the others may corrupt those tokens.
"""
from __future__ import annotations
import re

from ai.evaluation.metrics import TECHNICAL_TOKEN_PATTERNS

_GLYPH_FIXES = (
    (re.compile(r"\s{2,}"), " "),
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r"([,.;:!?])(?=[A-Za-z])"), r"\1 "),
)


def rule_based_correct(text: str) -> str:
    result = text
    for pattern, replacement in _GLYPH_FIXES:
        result = pattern.sub(replacement, result)
    return result.strip()


def mask_technical_tokens(text: str) -> tuple[str, dict[str, str]]:
    """Replaces every technical-token match with a unique placeholder so downstream
    correction can't alter it, returning the restore map keyed by placeholder."""
    restore: dict[str, str] = {}
    masked = text
    counter = 0
    for pattern in TECHNICAL_TOKEN_PATTERNS.values():
        def _sub(match: re.Match) -> str:
            nonlocal counter
            counter += 1
            token = f"__TOK{counter}__"
            restore[token] = match.group(0)
            return token
        masked = pattern.sub(_sub, masked)
    return masked, restore


def restore_technical_tokens(text: str, restore: dict[str, str]) -> str:
    result = text
    for token, original in restore.items():
        result = result.replace(token, original)
    return result


def symspell_correct(text: str) -> str:
    from symspellpy import SymSpell, Verbosity  # noqa: F401 — optional dependency
    import pkg_resources
    sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    dictionary_path = pkg_resources.resource_filename("symspellpy", "frequency_dictionary_en_82_765.txt")
    sym.load_dictionary(dictionary_path, term_index=0, count_index=1)
    words = []
    for word in text.split():
        suggestions = sym.lookup(word.lower(), Verbosity.CLOSEST, max_edit_distance=2)
        words.append(suggestions[0].term if suggestions else word)
    return " ".join(words)


_transformer_pipeline = None


def transformer_correct(text: str) -> str:
    global _transformer_pipeline
    if _transformer_pipeline is None:
        from transformers import pipeline  # noqa: F401 — optional dependency
        _transformer_pipeline = pipeline("text2text-generation", model="oliverguhr/spelling-correction-english-base")
    return _transformer_pipeline(text, max_length=512)[0]["generated_text"]


def hybrid_correct(text: str, underlying: str = "rule_based") -> str:
    masked, restore = mask_technical_tokens(text)
    corrector = {"rule_based": rule_based_correct, "symspell": symspell_correct, "transformer": transformer_correct}[underlying]
    corrected = corrector(masked)
    return restore_technical_tokens(corrected, restore)


METHODS = {
    "rule_based": rule_based_correct,
    "symspell": symspell_correct,
    "transformer": transformer_correct,
    "hybrid": hybrid_correct,
}
