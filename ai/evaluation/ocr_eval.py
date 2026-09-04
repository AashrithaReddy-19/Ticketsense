"""OCR engine comparison CLI (Phase 10).

Compares Tesseract, EasyOCR, PaddleOCR and TrOCR on a labelled dataset of
(image_path, ground_truth_text) pairs and prints real CER/WER/latency numbers —
never simulated ones. Tesseract is a core dependency (already installed via the
backend Dockerfile's apt package); EasyOCR/PaddleOCR/TrOCR are optional and only
imported when selected, so this file itself always imports cleanly.

Dataset format: a JSONL file, one object per line:
    {"image_path": "samples/ticket_001.png", "text": "ground truth transcription", "error_codes": ["ERR-4042"]}
`error_codes` is optional; when present, error-code accuracy is also reported.

Usage:
    uv run python ai/evaluation/ocr_eval.py --dataset path/to/labels.jsonl --engines tesseract
    uv run python ai/evaluation/ocr_eval.py --dataset path/to/labels.jsonl --engines tesseract,easyocr,paddleocr,trocr

If no --dataset is given, or the file has zero usable rows, this script refuses to
print a comparison table rather than fabricate one — see the "insufficient data"
message it prints instead.
"""
import argparse
import json
import time
from pathlib import Path
from typing import Callable

from ai.evaluation.metrics import character_error_rate, error_code_accuracy, word_error_rate

ENGINES: dict[str, str] = {
    "tesseract": "Tesseract (pytesseract) — installed by default",
    "easyocr": "EasyOCR — optional, pip install easyocr",
    "paddleocr": "PaddleOCR — optional, pip install paddleocr",
    "trocr": "TrOCR (transformers) — optional, pip install transformers torch",
}


def _load_dataset(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line: continue
        row = json.loads(line)
        if "image_path" not in row or "text" not in row: continue
        rows.append(row)
    return rows


def _engine_reader(name: str) -> Callable[[bytes], str]:
    if name == "tesseract":
        import pytesseract
        from PIL import Image
        import io
        def read(data: bytes) -> str: return pytesseract.image_to_string(Image.open(io.BytesIO(data)))
        return read
    if name == "easyocr":
        import easyocr  # noqa: F401 — optional dependency, import failure is the point
        reader = easyocr.Reader(["en"], gpu=False)
        def read(data: bytes) -> str:
            import numpy as np
            from PIL import Image
            import io
            image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
            return " ".join(reader.readtext(image, detail=0))
        return read
    if name == "paddleocr":
        from paddleocr import PaddleOCR  # noqa: F401
        engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        def read(data: bytes) -> str:
            import numpy as np
            from PIL import Image
            import io
            image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
            result = engine.ocr(image, cls=True)
            return " ".join(line[1][0] for block in (result or []) for line in block)
        return read
    if name == "trocr":
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel  # noqa: F401
        processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-printed")
        model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-printed")
        def read(data: bytes) -> str:
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(data)).convert("RGB")
            pixel_values = processor(images=image, return_tensors="pt").pixel_values
            ids = model.generate(pixel_values)
            return processor.batch_decode(ids, skip_special_tokens=True)[0]
        return read
    raise ValueError(f"Unknown OCR engine: {name}")


def evaluate_engine(name: str, dataset: list[dict], base_dir: Path) -> dict:
    try:
        read = _engine_reader(name)
    except ImportError as exc:
        return {"engine": name, "available": False, "reason": str(exc)}
    cer, wer, code_acc, latencies, failures = [], [], [], [], 0
    started_total = time.monotonic()
    for row in dataset:
        image_path = base_dir / row["image_path"]
        if not image_path.exists(): failures += 1; continue
        started = time.monotonic()
        try:
            hypothesis = read(image_path.read_bytes())
        except Exception:
            failures += 1; continue
        latencies.append(time.monotonic() - started)
        cer.append(character_error_rate(hypothesis, row["text"]))
        wer.append(word_error_rate(hypothesis, row["text"]))
        if row.get("error_codes"):
            acc = error_code_accuracy(hypothesis, " ".join(row["error_codes"]))
            if acc is not None: code_acc.append(acc)
    n = len(cer)
    return {
        "engine": name, "available": True, "samples": n, "failures": failures,
        "mean_cer": round(sum(cer) / n, 4) if n else None,
        "mean_wer": round(sum(wer) / n, 4) if n else None,
        "error_code_accuracy": round(sum(code_acc) / len(code_acc), 4) if code_acc else None,
        "mean_latency_ms": round(1000 * sum(latencies) / n, 1) if n else None,
        "total_runtime_s": round(time.monotonic() - started_total, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, help="JSONL file of {image_path, text, error_codes?} rows")
    parser.add_argument("--engines", default="tesseract", help="Comma-separated: tesseract,easyocr,paddleocr,trocr")
    parser.add_argument("--split", default="full", help="Label only — records which dataset split this run covers")
    args = parser.parse_args()

    if not args.dataset or not args.dataset.exists():
        print("No --dataset provided (or file not found). Refusing to print a fabricated comparison.")
        print("Supply a JSONL file of {\"image_path\":..., \"text\":..., \"error_codes\":[...]} rows to run a real evaluation.")
        return
    dataset = _load_dataset(args.dataset)
    if not dataset:
        print(f"{args.dataset} contains zero usable labelled rows. Refusing to print a fabricated comparison.")
        return

    base_dir = args.dataset.parent
    for name in [e.strip() for e in args.engines.split(",") if e.strip()]:
        result = evaluate_engine(name, dataset, base_dir)
        print(f"\nModel/method: {result['engine']}")
        print(f"Dataset split: {args.split}")
        if not result["available"]:
            print(f"Status: not installed ({ENGINES.get(name, 'unknown engine')})")
            print(f"Reason: {result['reason']}")
            continue
        print(f"Number of samples evaluated: {result['samples']} (skipped: {result['failures']})")
        print(f"Mean character error rate (CER): {result['mean_cer']}")
        print(f"Mean word error rate (WER): {result['mean_wer']}")
        print(f"Error-code accuracy: {result['error_code_accuracy']}")
        print(f"Mean latency per sample (ms): {result['mean_latency_ms']}")
        print(f"Total runtime (s): {result['total_runtime_s']}")


if __name__ == "__main__":
    main()
