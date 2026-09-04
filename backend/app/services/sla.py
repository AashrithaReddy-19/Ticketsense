"""Section 15: SLA due-date computation and transparent breach-risk classification.

``sla_policies`` rows are matched by tenant + priority. When no active policy
exists for a priority — true for any tenant that hasn't configured one yet —
a documented, honestly-labelled default resolution window is used instead.
This is a rules-based fallback, never presented as a trained prediction.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import SLAPolicy

DEFAULT_RESOLUTION_MINUTES = {"urgent": 4 * 60, "high": 8 * 60, "medium": 24 * 60, "low": 72 * 60}


async def resolution_minutes_for(db: AsyncSession, tenant_id, priority: str) -> tuple[int, bool]:
    """Returns (minutes, from_configured_policy)."""
    policy = await db.scalar(
        select(SLAPolicy).where(SLAPolicy.tenant_id == tenant_id, SLAPolicy.priority == priority, SLAPolicy.is_active.is_(True))
    )
    if policy:
        return policy.resolution_minutes, True
    return DEFAULT_RESOLUTION_MINUTES.get(priority, DEFAULT_RESOLUTION_MINUTES["medium"]), False


async def compute_sla_due_at(db: AsyncSession, tenant_id, priority: str, created_at: datetime) -> datetime:
    minutes, _ = await resolution_minutes_for(db, tenant_id, priority)
    return created_at + timedelta(minutes=minutes)


def breach_risk(sla_due_at: datetime | None, created_at: datetime | None = None, now: datetime | None = None) -> dict:
    """A transparent time-remaining classification — not a learned prediction.

    ``status`` is one of on_track / at_risk / breached. "At risk" means inside
    the final 20% of the resolution window (or already overdue). Without
    ``created_at`` the window's start is unknown, so risk falls back to an
    absolute one-hour-remaining threshold rather than a window percentage.
    """
    if sla_due_at is None:
        return {"status": "unknown", "minutes_remaining": None, "percent_remaining": None}
    now = now or datetime.now(timezone.utc)
    minutes_remaining = (sla_due_at - now).total_seconds() / 60
    if minutes_remaining <= 0:
        return {"status": "breached", "minutes_remaining": round(minutes_remaining, 1), "percent_remaining": 0.0}
    if created_at is not None:
        total_minutes = (sla_due_at - created_at).total_seconds() / 60
        percent_remaining = max(0.0, min(1.0, minutes_remaining / total_minutes)) if total_minutes > 0 else 0.0
        status = "at_risk" if percent_remaining <= 0.2 else "on_track"
        return {"status": status, "minutes_remaining": round(minutes_remaining, 1), "percent_remaining": round(percent_remaining, 3)}
    status = "at_risk" if minutes_remaining <= 60 else "on_track"
    return {"status": status, "minutes_remaining": round(minutes_remaining, 1), "percent_remaining": None}
