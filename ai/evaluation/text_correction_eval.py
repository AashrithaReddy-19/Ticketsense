"""Corrupted-text correction method comparison CLI (Phase 10).

Compares rule_based, symspell, transformer and hybrid correction on a labelled
dataset of (corrupted_text, correct_text) pairs, reporting real CER/WER reduction
and technical-token preservation — never simulated numbers.

Dataset format: a JSONL file, one object per line:
    {"corrupted": "cl1ck  reconnect  ,then check ERR-4042 at 10.0.0.5", "correct": "Click reconnect, then check ERR-4042 at 10.0.0.5"}

Usage:
    uv run python ai/evaluation/text_correction_eval.py --dataset path/to/pairs.jsonl --methods rule_based,hybrid
"""
import argparse
import json
import time
from pathlib import Path

from ai.evaluation.metrics import character_error_rate, technical_token_preservation, word_error_rate
from ai.evaluation.text_correction import METHODS

OPTIONAL = {"symspell": "pip install symspellpy", "transformer": "pip install transformers torch"}


def _load_dataset(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line: continue
        row = json.loads(line)
        if "corrupted" in row and "correct" in row: rows.append(row)
    return rows


def evaluate_method(name: str, dataset: list[dict]) -> dict:
    corrector = METHODS[name]
    cer_before, cer_after, wer_before, wer_after, preservation, failures = [], [], [], [], [], 0
    started_total = time.monotonic()
    for row in dataset:
        try:
            corrected = corrector(row["corrupted"])
        except ImportError as exc:
            return {"method": name, "available": False, "reason": str(exc)}
        except Exception:
            failures += 1; continue
        cer_before.append(character_error_rate(row["corrupted"], row["correct"]))
        cer_after.append(character_error_rate(corrected, row["correct"]))
        wer_before.append(word_error_rate(row["corrupted"], row["correct"]))
        wer_after.append(word_error_rate(corrected, row["correct"]))
        preserved = technical_token_preservation(row["correct"], corrected)
        if preserved: preservation.append(sum(preserved.values()) / len(preserved))
    n = len(cer_after)
    return {
        "method": name, "available": True, "samples": n, "failures": failures,
        "mean_cer_before": round(sum(cer_before) / n, 4) if n else None,
        "mean_cer_after": round(sum(cer_after) / n, 4) if n else None,
        "mean_wer_before": round(sum(wer_before) / n, 4) if n else None,
        "mean_wer_after": round(sum(wer_after) / n, 4) if n else None,
        "technical_token_preservation": round(sum(preservation) / len(preservation), 4) if preservation else None,
        "total_runtime_s": round(time.monotonic() - started_total, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, help="JSONL file of {corrupted, correct} pairs")
    parser.add_argument("--methods", default="rule_based,hybrid", help="Comma-separated: rule_based,symspell,transformer,hybrid")
    parser.add_argument("--split", default="full")
    args = parser.parse_args()

    if not args.dataset or not args.dataset.exists():
        print("No --dataset provided (or file not found). Refusing to print a fabricated comparison.")
        print('Supply a JSONL file of {"corrupted":..., "correct":...} pairs to run a real evaluation.')
        return
    dataset = _load_dataset(args.dataset)
    if not dataset:
        print(f"{args.dataset} contains zero usable labelled rows. Refusing to print a fabricated comparison.")
        return

    for name in [m.strip() for m in args.methods.split(",") if m.strip()]:
        if name not in METHODS:
            print(f"\nUnknown method: {name} (choices: {', '.join(METHODS)})"); continue
        result = evaluate_method(name, dataset)
        print(f"\nModel/method: {result['method']}")
        print(f"Dataset split: {args.split}")
        if not result["available"]:
            print(f"Status: not installed ({OPTIONAL.get(name, 'optional dependency')})")
            print(f"Reason: {result['reason']}")
            continue
        print(f"Number of samples evaluated: {result['samples']} (skipped: {result['failures']})")
        print(f"Mean CER before -> after: {result['mean_cer_before']} -> {result['mean_cer_after']}")
        print(f"Mean WER before -> after: {result['mean_wer_before']} -> {result['mean_wer_after']}")
        print(f"Technical token preservation: {result['technical_token_preservation']}")
        print(f"Total runtime (s): {result['total_runtime_s']}")


if __name__ == "__main__":
    main()
