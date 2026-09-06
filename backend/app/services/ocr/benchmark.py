"""V2 Phase 11: reproducible OCR benchmark runs.

Every metric here (character/word error rate, latency) is computed by
``ai.evaluation.metrics`` from a real engine call against a real stored
image and a real curated ground-truth string — never simulated. An engine
that fails to import, or that raises mid-run, produces an honestly labelled
``engine_unavailable``/``failed`` run rather than a fabricated score."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.evaluation.metrics import character_error_rate, word_error_rate
from app.models.ocr_benchmark import OcrBenchmarkCase, OcrBenchmarkResult, OcrBenchmarkRun
from app.services.attachment_storage import storage
from app.services.ocr.engines import available_engines, run_engine

MIN_CASES = 3


class OcrBenchmarkError(Exception):
    pass


async def add_case(db: AsyncSession, tenant_id: UUID, dataset_id: UUID, user_id: UUID, image_bytes: bytes,
                    ground_truth_text: str, tags: list | None = None, extension: str = ".png") -> OcrBenchmarkCase:
    key = storage.save(tenant_id, image_bytes, extension)
    case = OcrBenchmarkCase(
        dataset_id=dataset_id, tenant_id=tenant_id, storage_key=key,
        image_sha256=hashlib.sha256(image_bytes).hexdigest(), ground_truth_text=ground_truth_text,
        source_label="synthetic", tags=tags or [], created_by=user_id,
    )
    db.add(case)
    await db.flush()
    return case


async def _unresolved_run(db: AsyncSession, tenant_id: UUID, dataset_id: UUID, engine: str, status: str,
                           reason: str, row_count: int, probe_info: dict, started: datetime, user_id: UUID) -> OcrBenchmarkRun:
    run = OcrBenchmarkRun(
        tenant_id=tenant_id, dataset_id=dataset_id, engine=engine, status=status, unavailable_reason=reason,
        row_count_considered=row_count, environment_info={"probe": probe_info}, started_at=started,
        completed_at=datetime.now(timezone.utc), created_by=user_id,
    )
    db.add(run)
    await db.flush()
    return run


async def run_benchmark(db: AsyncSession, tenant_id: UUID, dataset_id: UUID, engine: str, user_id: UUID) -> OcrBenchmarkRun:
    started = datetime.now(timezone.utc)
    availability = available_engines()
    if engine not in availability:
        raise OcrBenchmarkError(f"Unknown OCR engine: {engine}")

    probe_info = availability[engine]
    if not probe_info["available"]:
        return await _unresolved_run(db, tenant_id, dataset_id, engine, "engine_unavailable", probe_info["reason"], 0, probe_info, started, user_id)

    cases = (await db.scalars(
        select(OcrBenchmarkCase).where(OcrBenchmarkCase.dataset_id == dataset_id, OcrBenchmarkCase.tenant_id == tenant_id)
    )).all()
    if len(cases) < MIN_CASES:
        reason = f"Only {len(cases)} ground-truth case(s) registered; at least {MIN_CASES} are required for a meaningful benchmark."
        return await _unresolved_run(db, tenant_id, dataset_id, engine, "insufficient_data", reason, len(cases), probe_info, started, user_id)

    run = OcrBenchmarkRun(
        tenant_id=tenant_id, dataset_id=dataset_id, engine=engine, status="completed",
        row_count_considered=len(cases), environment_info={"probe": probe_info}, started_at=started, created_by=user_id,
    )
    db.add(run)
    await db.flush()

    cers, wers, latencies = [], [], []
    for case in cases:
        image_bytes = storage.read(case.storage_key)
        try:
            extracted_text, latency_ms = run_engine(engine, image_bytes)
        except Exception as exc:
            run.status = "failed"
            run.unavailable_reason = f"The engine raised an error while processing case {case.id}: {exc}"
            run.completed_at = datetime.now(timezone.utc)
            await db.flush()
            return run
        cer = character_error_rate(extracted_text, case.ground_truth_text)
        wer = word_error_rate(extracted_text, case.ground_truth_text)
        db.add(OcrBenchmarkResult(run_id=run.id, case_id=case.id, extracted_text=extracted_text,
                                   character_error_rate=cer, word_error_rate=wer, latency_ms=latency_ms))
        cers.append(cer); wers.append(wer); latencies.append(latency_ms)

    run.mean_character_error_rate = sum(cers) / len(cers)
    run.mean_word_error_rate = sum(wers) / len(wers)
    run.mean_latency_ms = sum(latencies) / len(latencies)
    run.completed_at = datetime.now(timezone.utc)
    await db.flush()
    return run
