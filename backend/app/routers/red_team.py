"""TicketSense V2 red-team lab API. Every run's cases execute against real
defense mechanisms with synthetic adversarial inputs only — see
app.services.red_team.cases. Results here are never inserted into the
production knowledge corpus and never sent to a customer.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog
from app.models.red_team import RedTeamRun
from app.models.user import User
from app.services.feature_flags import require_feature
from app.services.red_team.runner import run_suite, summarize_run

router = APIRouter(prefix="/api/v2/red-team", tags=["v2-red-team"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "red_team_lab", user, permissions)


@router.post("/runs", status_code=201)
async def create_run(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "red_team:manage")
    await require_flag(db, user)
    run = await run_suite(db, user.tenant_id, user.id)
    summary = await summarize_run(db, run)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.red_team.run_executed", resource_type="red_team_run", resource_id=str(run.id), metadata_json={"attack_success_rate": summary["attack_success_rate"], "applicable_cases": summary["applicable_cases"]}))
    await db.commit()
    return summary


@router.get("/runs")
async def list_runs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "red_team:read")
    await require_flag(db, user)
    total = int(await db.scalar(select(func.count()).select_from(RedTeamRun).where(RedTeamRun.tenant_id == user.tenant_id)) or 0)
    rows = (await db.scalars(select(RedTeamRun).where(RedTeamRun.tenant_id == user.tenant_id).order_by(RedTeamRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [{"id": r.id, "suite_version": r.suite_version, "status": r.status, "started_at": r.started_at, "completed_at": r.completed_at} for r in rows], "page": page, "page_size": page_size, "total": total}


@router.get("/runs/{run_id}")
async def run_detail(run_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "red_team:read")
    await require_flag(db, user)
    run = await db.scalar(select(RedTeamRun).where(RedTeamRun.id == run_id, RedTeamRun.tenant_id == user.tenant_id))
    if not run:
        raise HTTPException(404, "Red-team run not found")
    return await summarize_run(db, run)
