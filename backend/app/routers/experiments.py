"""TicketSense V2 shadow-mode and champion/challenger experiment API.

Every endpoint here is read/measure-only with one narrow exception — the
health-check rollback — which only ever retreats to a previously-approved
champion, never promotes a challenger. Promotion always remains a separate,
explicit Admin action (POST /api/v2/models/{id}/promote) gated on an
Admin-recorded evaluation_status, per app.routers.v2_governance.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog
from app.models.user import User
from app.services.experiments.shadow import check_champion_health_and_rollback, compare_champion_challenger, run_shadow_sample
from app.services.feature_flags import require_feature

router = APIRouter(prefix="/api/v2/experiments", tags=["v2-experiments"])

TASK_TYPES = ("department", "priority", "sentiment")


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag(db: AsyncSession, user: User, flag: str) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, flag, user, permissions)


class ShadowSampleRequest(BaseModel):
    task_type: str = Field(pattern="^(department|priority|sentiment)$")
    sample_size: int = Field(default=20, ge=1, le=200)


@router.post("/shadow-runs", status_code=201)
async def create_shadow_sample(payload: ShadowSampleRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "model:manage")
    await require_flag(db, user, "shadow_mode")
    result = await run_shadow_sample(db, user.tenant_id, payload.task_type, payload.sample_size, user.id)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.experiment.shadow_sampled", resource_type="shadow_run", resource_id=None, metadata_json={"task_type": payload.task_type, **{k: v for k, v in result.items() if k not in ("champion_model_id", "challenger_model_id")}}))
    await db.commit()
    return result


@router.get("/compare")
async def compare(task_type: str = Query(..., pattern="^(department|priority|sentiment)$"), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "model:read")
    await require_flag(db, user, "challenger_models")
    return await compare_champion_challenger(db, user.tenant_id, task_type)


class HealthCheckRequest(BaseModel):
    task_type: str = Field(pattern="^(department|priority|sentiment)$")


@router.post("/champion-health-check")
async def champion_health_check(payload: HealthCheckRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "model:manage")
    await require_flag(db, user, "challenger_models")
    result = await check_champion_health_and_rollback(db, user.tenant_id, payload.task_type, user.id)
    from_model_id = result.get("from_model_id")
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.experiment.champion_health_checked", resource_type="provider_model", resource_id=str(from_model_id) if from_model_id else None, metadata_json={"task_type": payload.task_type, "action": result["action"], "reason": result["reason"]}))
    await db.commit()
    return result
