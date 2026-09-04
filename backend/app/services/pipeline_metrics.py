"""Structured per-stage timing for the ticket-intake and drafting pipelines (Phase 12).

Callers collect (stage, started_at, ended_at, duration_ms, success, error_category)
tuples with `stage_timer`, then persist them as `PipelineMetric` rows once a ticket_id
is known. Recording is best-effort from the caller's perspective — a metrics write
failure must never fail the request that produced it — and rows never carry ticket
subject/description text, only stage name, timing and outcome, so this data stays
safe to inspect broadly (dashboards, ops tooling) without touching customer content.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from uuid import UUID

from app.models.operations import PipelineMetric


@dataclass
class StageTiming:
    stage: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    success: bool
    error_category: str | None = None
    provider_version: str | None = None


@contextmanager
def stage_timer(stage: str, timings: list[StageTiming], provider_version: str | None = None):
    started_at = datetime.now(timezone.utc)
    started = monotonic()
    error_category = None
    try:
        yield
    except Exception as exc:
        error_category = type(exc).__name__
        raise
    finally:
        timings.append(StageTiming(
            stage=stage, started_at=started_at, ended_at=datetime.now(timezone.utc),
            duration_ms=round((monotonic() - started) * 1000), success=error_category is None,
            error_category=error_category, provider_version=provider_version,
        ))


def persist_stage_timings(db, tenant_id: UUID, ticket_id: UUID | None, trace_id: UUID, timings: list[StageTiming]) -> None:
    for timing in timings:
        db.add(PipelineMetric(
            tenant_id=tenant_id, ticket_id=ticket_id, trace_id=trace_id, stage=timing.stage,
            started_at=timing.started_at, ended_at=timing.ended_at, duration_ms=timing.duration_ms,
            success=timing.success, provider_version=timing.provider_version, error_category=timing.error_category,
        ))
