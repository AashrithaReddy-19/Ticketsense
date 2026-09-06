"""TicketSense V2 process mining API. Every run is computed from the real,
immutable ticket_events log — variant sequences and bottleneck durations
are never predicted or fabricated, and a tenant with too little history
gets an honest insufficient_data run. See app.services.process_mining."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog
from app.models.process_mining import ProcessMiningRun
from app.models.user import User
from app.services.feature_flags import require_feature
from app.services.process_mining.analysis import run_process_mining

router = APIRouter(prefix="/api/v2/process-mining", tags=["v2-process-mining"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "process_mining", user, permissions)


def run_json(row: ProcessMiningRun) -> dict:
    return {
        "id": row.id, "status": row.status, "ticket_count_considered": row.ticket_count_considered,
        "event_count_considered": row.event_count_considered, "variants": row.variants,
        "bottlenecks": row.bottlenecks, "insufficiency_reason": row.insufficiency_reason,
        "started_at": row.started_at, "completed_at": row.completed_at, "created_at": row.created_at,
    }


@router.post("/runs", status_code=201)
async def create_run(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "process_mining:manage")
    await require_flag(db, user)
    run = await run_process_mining(db, user.tenant_id, user.id)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.process_mining.run_created", resource_type="process_mining_run", resource_id=str(run.id), metadata_json={"status": run.status, "ticket_count_considered": run.ticket_count_considered}))
    await db.commit(); await db.refresh(run)
    return run_json(run)


@router.get("/runs")
async def list_runs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "process_mining:read")
    await require_flag(db, user)
    query = select(ProcessMiningRun).where(ProcessMiningRun.tenant_id == user.tenant_id)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await db.scalars(query.order_by(ProcessMiningRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [run_json(r) for r in rows], "page": page, "page_size": page_size, "total": total}


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "process_mining:read")
    await require_flag(db, user)
    run = await db.scalar(select(ProcessMiningRun).where(ProcessMiningRun.id == run_id, ProcessMiningRun.tenant_id == user.tenant_id))
    if not run:
        raise HTTPException(404, "Run not found")
    return run_json(run)
