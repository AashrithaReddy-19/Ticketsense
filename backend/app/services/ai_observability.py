"""Measured AI provider usage. Missing token/cost values remain NULL, never guessed."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.v2_governance import AIUsageEvent


async def usage_summary(db: AsyncSession, tenant_id, limit_days: int = 30) -> dict:
    window_start = datetime.now(timezone.utc) - timedelta(days=limit_days)
    rows = (await db.execute(
        select(
            AIUsageEvent.task_type,
            AIUsageEvent.provider,
            AIUsageEvent.model_version,
            func.count(AIUsageEvent.id),
            func.avg(AIUsageEvent.latency_ms),
            func.percentile_cont(.5).within_group(AIUsageEvent.latency_ms),
            func.percentile_cont(.95).within_group(AIUsageEvent.latency_ms),
            func.sum(AIUsageEvent.estimated_cost_usd),
            func.sum(case((AIUsageEvent.success.is_(False), 1), else_=0)),
            func.sum(case((AIUsageEvent.cache_hit.is_(True), 1), else_=0)),
        ).where(
            AIUsageEvent.tenant_id == tenant_id,
            AIUsageEvent.created_at >= window_start,
        ).group_by(AIUsageEvent.task_type, AIUsageEvent.provider, AIUsageEvent.model_version)
    )).all()
    return {"window_days": limit_days, "metrics_source": "persisted_ai_usage_events", "groups": [
        {"task_type": task, "provider": provider, "model_version": version, "calls": count,
         "latency_ms": {"average": round(float(avg), 2), "p50": round(float(p50), 2), "p95": round(float(p95), 2)},
         "measured_cost_usd": float(cost) if cost is not None else None,
         "failures": int(failures or 0), "cache_hits": int(cache_hits or 0)}
        for task, provider, version, count, avg, p50, p95, cost, failures, cache_hits in rows
    ], "empty_state": "No measured provider usage exists for this window." if not rows else None}
