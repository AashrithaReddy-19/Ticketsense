"""Real process mining over the existing, immutable ticket_events log.

Two textbook, dependency-free techniques, both computed purely from real
TicketEvent rows: variant discovery (the distinct event-type sequences
tickets actually followed, and how common each one is) and bottleneck
analysis (real elapsed-time statistics between consecutive event-type
pairs). Nothing here is predicted, inferred or simulated — a tenant with
too little event history gets an honest insufficient_data run, never a
fabricated variant or duration."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.process_mining import ProcessMiningRun
from app.models.response_draft import TicketEvent

MIN_TICKETS = 5
MAX_VARIANTS = 25
MAX_BOTTLENECK_PAIRS = 30


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


async def _load_traces(db: AsyncSession, tenant_id: UUID) -> dict[UUID, list[tuple[str, datetime]]]:
    rows = (await db.execute(
        select(TicketEvent.ticket_id, TicketEvent.event_type, TicketEvent.created_at)
        .where(TicketEvent.tenant_id == tenant_id)
        .order_by(TicketEvent.ticket_id, TicketEvent.created_at)
    )).all()
    traces: dict[UUID, list[tuple[str, datetime]]] = defaultdict(list)
    for ticket_id, event_type, created_at in rows:
        traces[ticket_id].append((event_type, created_at))
    return traces


def _compute_variants(traces: dict[UUID, list[tuple[str, datetime]]]) -> list[dict]:
    counts: dict[tuple[str, ...], int] = defaultdict(int)
    for events in traces.values():
        counts[tuple(event_type for event_type, _ in events)] += 1
    total = len(traces)
    variants = [
        {"sequence": list(sequence), "ticket_count": count, "percentage": round(count / total, 4)}
        for sequence, count in counts.items()
    ]
    variants.sort(key=lambda v: v["ticket_count"], reverse=True)
    return variants[:MAX_VARIANTS]


def _compute_bottlenecks(traces: dict[UUID, list[tuple[str, datetime]]]) -> list[dict]:
    durations: dict[tuple[str, str], list[float]] = defaultdict(list)
    for events in traces.values():
        for (from_type, from_time), (to_type, to_time) in zip(events, events[1:]):
            durations[(from_type, to_type)].append((to_time - from_time).total_seconds())
    bottlenecks = []
    for (from_type, to_type), values in durations.items():
        values.sort()
        bottlenecks.append({
            "from_event_type": from_type, "to_event_type": to_type, "sample_size": len(values),
            "mean_seconds": round(mean(values), 2),
            "median_seconds": round(_percentile(values, 0.5), 2),
            "p90_seconds": round(_percentile(values, 0.9), 2),
        })
    bottlenecks.sort(key=lambda b: b["mean_seconds"], reverse=True)
    return bottlenecks[:MAX_BOTTLENECK_PAIRS]


async def run_process_mining(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> ProcessMiningRun:
    started = datetime.now(timezone.utc)
    traces = await _load_traces(db, tenant_id)
    event_count = sum(len(events) for events in traces.values())

    if len(traces) < MIN_TICKETS:
        run = ProcessMiningRun(
            tenant_id=tenant_id, status="insufficient_data",
            ticket_count_considered=len(traces), event_count_considered=event_count,
            insufficiency_reason=f"Only {len(traces)} ticket(s) have any recorded events; at least {MIN_TICKETS} are required for meaningful variant/bottleneck analysis.",
            started_at=started, completed_at=datetime.now(timezone.utc), created_by=user_id,
        )
        db.add(run)
        await db.flush()
        return run

    run = ProcessMiningRun(
        tenant_id=tenant_id, status="completed",
        ticket_count_considered=len(traces), event_count_considered=event_count,
        variants=_compute_variants(traces), bottlenecks=_compute_bottlenecks(traces),
        started_at=started, completed_at=datetime.now(timezone.utc), created_by=user_id,
    )
    db.add(run)
    await db.flush()
    return run
