"""Pluggable OCR engine registry.

Each engine's availability is determined by a live import/probe attempt at
call time, never by a config flag alone — an engine whose Python package or
system binary isn't actually installed reports ``available: False`` with the
real exception text, matching the honest-unavailable pattern already used by
``ai/evaluation/ocr_eval.py``. Nothing here claims an engine "works" unless
it was just verified to import and respond."""
from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Callable

OCR_ENGINES = ("tesseract", "easyocr", "paddleocr")


@dataclass
class EngineProbe:
    available: bool
    reason: str | None
    reader: Callable[[bytes], str] | None = None


def probe_tesseract() -> EngineProbe:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception as exc:
        return EngineProbe(False, f"Tesseract is not installed or not on PATH in this environment: {exc}")

    def reader(image_bytes: bytes) -> str:
        import pytesseract
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as img:
            return pytesseract.image_to_string(img.convert("L"))

    return EngineProbe(True, None, reader)


def probe_easyocr() -> EngineProbe:
    try:
        import easyocr  # noqa: F401
    except ImportError as exc:
        return EngineProbe(False, f"The easyocr package is not installed in this environment: {exc}")

    def reader(image_bytes: bytes) -> str:
        import numpy as np
        import easyocr
        from PIL import Image
        reader_instance = easyocr.Reader(["en"], gpu=False)
        with Image.open(io.BytesIO(image_bytes)) as img:
            results = reader_instance.readtext(np.array(img.convert("RGB")), detail=0)
        return "\n".join(results)

    return EngineProbe(True, None, reader)


def probe_paddleocr() -> EngineProbe:
    try:
        import paddleocr  # noqa: F401
    except ImportError as exc:
        return EngineProbe(False, f"The paddleocr package is not installed in this environment: {exc}")

    def reader(image_bytes: bytes) -> str:
        import numpy as np
        from paddleocr import PaddleOCR
        from PIL import Image
        engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        with Image.open(io.BytesIO(image_bytes)) as img:
            results = engine.ocr(np.array(img.convert("RGB")), cls=True)
        lines = [line[1][0] for block in (results or []) for line in block]
        return "\n".join(lines)

    return EngineProbe(True, None, reader)


_PROBES: dict[str, Callable[[], EngineProbe]] = {
    "tesseract": probe_tesseract,
    "easyocr": probe_easyocr,
    "paddleocr": probe_paddleocr,
}


def available_engines() -> dict[str, dict]:
    """Real, live availability of every registered engine — never cached, never assumed."""
    return {name: {"available": probe().available, "reason": probe().reason} for name, probe in _PROBES.items()}


def get_probe(engine: str) -> EngineProbe:
    if engine not in _PROBES:
        raise ValueError(f"Unknown OCR engine: {engine}")
    return _PROBES[engine]()


def run_engine(engine: str, image_bytes: bytes) -> tuple[str, float]:
    """Runs one engine against one image. Raises if the engine is unavailable —
    callers must check availability first and never call this speculatively."""
    probe = get_probe(engine)
    if not probe.available or probe.reader is None:
        raise RuntimeError(probe.reason or f"{engine} is not available")
    started = time.perf_counter()
    text = probe.reader(image_bytes)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return text, elapsed_ms
