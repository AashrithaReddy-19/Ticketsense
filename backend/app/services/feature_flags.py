"""Deterministic, server-side feature flag evaluation with fail-closed defaults."""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.v2_governance import FeatureFlag, FeatureFlagOverride
from app.models.user import User


@dataclass(frozen=True)
class FlagDecision:
    key: str
    enabled: bool
    reason_code: str
    reason: str
    source: str
    rollout_bucket: int | None = None
    rollout_percentage: int | None = None


def stable_bucket(key: str, tenant_id: object, user_id: object) -> int:
    digest = sha256(f"{key}:{tenant_id}:{user_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 100


def _active(starts_at, ends_at, now: datetime) -> bool:
    return (starts_at is None or starts_at <= now) and (ends_at is None or ends_at > now)


def _specificity(override: FeatureFlagOverride) -> int:
    return {"user": 50, "department": 40, "capability": 30, "role": 20, "tenant": 10}.get(override.scope_type, 0)


async def evaluate_flag(db: AsyncSession, key: str, user: User, permissions: list[str] | None = None, _seen: set[str] | None = None) -> FlagDecision:
    flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
    if not flag:
        return FlagDecision(key, False, "UNKNOWN_FLAG", "The feature is not registered.", "fail_closed")
    if flag.kill_switch:
        return FlagDecision(key, False, "KILL_SWITCH", "The global kill switch is active.", "global_kill_switch")
    now = datetime.now(timezone.utc)
    if not _active(flag.starts_at, flag.ends_at, now):
        return FlagDecision(key, False, "OUTSIDE_ACTIVE_WINDOW", "The feature is outside its configured active window.", "flag_schedule")
    seen = set(_seen or ())
    if key in seen:
        return FlagDecision(key, False, "PREREQUISITE_CYCLE", "A prerequisite cycle was detected.", "fail_closed")
    seen.add(key)
    for prerequisite in flag.prerequisites or []:
        result = await evaluate_flag(db, str(prerequisite), user, permissions, seen)
        if not result.enabled:
            return FlagDecision(key, False, "PREREQUISITE_DISABLED", f"Prerequisite '{prerequisite}' is disabled.", "prerequisite")
    rows = list((await db.scalars(select(FeatureFlagOverride).where(
        FeatureFlagOverride.flag_id == flag.id,
        FeatureFlagOverride.tenant_id == user.tenant_id,
    ))).all())
    capabilities = set(permissions or [])
    matches = []
    for row in rows:
        if not _active(row.starts_at, row.ends_at, now):
            continue
        match = row.scope_type == "tenant" and row.scope_value == str(user.tenant_id)
        match = match or row.scope_type == "department" and row.scope_value == str(user.department_id)
        match = match or row.scope_type == "user" and row.scope_value == str(user.id)
        match = match or row.scope_type == "role" and row.scope_value == user.role
        match = match or row.scope_type == "capability" and row.scope_value in capabilities
        if match:
            matches.append(row)
    selected = max(matches, key=lambda item: (_specificity(item), item.updated_at or item.created_at, str(item.id)), default=None)
    enabled = bool(selected.enabled) if selected else bool(flag.global_default)
    source = f"{selected.scope_type}_override" if selected else "global_default"
    if not enabled:
        return FlagDecision(key, False, "DISABLED", f"Feature is disabled by {source.replace('_', ' ')}.", source)
    percentage = selected.rollout_percentage if selected else 100
    bucket = stable_bucket(key, user.tenant_id, user.id)
    if bucket >= percentage:
        return FlagDecision(key, False, "ROLLOUT_EXCLUDED", f"Stable rollout bucket {bucket} is outside {percentage}% rollout.", source, bucket, percentage)
    return FlagDecision(key, True, "ENABLED", f"Enabled by {source.replace('_', ' ')}; stable rollout bucket {bucket} is within {percentage}%.", source, bucket, percentage)


async def require_feature(db: AsyncSession, key: str, user: User, permissions: list[str] | None = None) -> FlagDecision:
    from fastapi import HTTPException
    result = await evaluate_flag(db, key, user, permissions)
    if not result.enabled:
        raise HTTPException(404, f"Feature '{key}' is unavailable")
    return result
