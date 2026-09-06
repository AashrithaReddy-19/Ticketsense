"""TicketSense V2 adaptive threshold simulation.

Every simulation is read-only: it estimates what a proposed confidence
threshold would have meant for real historical `TicketDecision` rows, and is
persisted purely as an auditable record of what was simulated. There is no
endpoint, here or anywhere else, that applies a simulated threshold to a
live `DepartmentResolutionPolicy` — promotion of any such change is a
deliberate future decision left to an explicit, separately-approved policy
change, exactly as the spec requires ("No automatic policy deployment").
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.department import Department
from app.models.enterprise import ResolutionConfirmation, TicketDecision
from app.models.evaluation import ThresholdSimulation
from app.models.platform import AuditLog
from app.models.ticket import Ticket
from app.models.user import User
from app.services.evaluation.threshold_simulation import DecisionRecord, simulate
from app.services.feature_flags import require_feature

router = APIRouter(prefix="/api/v2/adaptive-thresholds", tags=["v2-adaptive-thresholds"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag_enabled(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "adaptive_thresholds", user, permissions)


class SimulationRequest(BaseModel):
    proposed_threshold: float = Field(ge=0.0, le=1.0)
    department_id: UUID | None = None
    category: str | None = Field(default=None, max_length=120)


def simulation_json(row: ThresholdSimulation) -> dict:
    return {
        "id": row.id, "department_id": row.department_id, "category": row.category,
        "proposed_threshold": float(row.proposed_threshold), "sample_size": row.sample_size,
        "auto_resolved_at_threshold": row.auto_resolved_at_threshold, "data_sufficient": row.data_sufficient,
        "insufficiency_reasons": row.insufficiency_reasons,
        "estimated_coverage": float(row.estimated_coverage) if row.estimated_coverage is not None else None,
        "estimated_referral_rate": float(row.estimated_referral_rate) if row.estimated_referral_rate is not None else None,
        "historical_false_resolution_rate": float(row.historical_false_resolution_rate) if row.historical_false_resolution_rate is not None else None,
        "confidence_interval": [float(row.confidence_interval_low), float(row.confidence_interval_high)] if row.confidence_interval_low is not None else None,
        "sensitive_category_override": row.sensitive_category_override, "based_on": row.based_on,
        "created_at": row.created_at,
    }


@router.post("/simulate", status_code=201)
async def create_simulation(payload: SimulationRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "threshold:simulate")
    await require_flag_enabled(db, user)

    department_name = None
    if payload.department_id:
        department = await db.scalar(select(Department).where(Department.id == payload.department_id, Department.tenant_id == user.tenant_id))
        if not department:
            raise HTTPException(422, "Department is outside this tenant")
        department_name = department.name

    needs_help_exists = exists(
        select(ResolutionConfirmation.id).where(
            ResolutionConfirmation.ticket_id == Ticket.id, ResolutionConfirmation.outcome == "needs_help"
        )
    )
    query = (
        select(TicketDecision.overall_confidence, TicketDecision.decision, Ticket.reopened_count, needs_help_exists)
        .join(Ticket, Ticket.id == TicketDecision.ticket_id)
        .where(Ticket.tenant_id == user.tenant_id, TicketDecision.overall_confidence.isnot(None))
    )
    if payload.department_id:
        query = query.where(Ticket.department_id == payload.department_id)
    if payload.category:
        query = query.where(Ticket.category == payload.category)

    rows = (await db.execute(query)).all()
    records = [
        DecisionRecord(
            confidence=float(confidence), was_auto_resolved=(decision == "auto_resolve"),
            was_false_resolution=bool(reopened_count > 0 or needs_help),
        )
        for confidence, decision, reopened_count, needs_help in rows
    ]

    result = simulate(records, payload.proposed_threshold, category=payload.category, department_name=department_name)

    row = ThresholdSimulation(
        tenant_id=user.tenant_id, department_id=payload.department_id, category=payload.category,
        proposed_threshold=payload.proposed_threshold, sample_size=result["sample_size"],
        auto_resolved_at_threshold=result["auto_resolved_at_threshold"], data_sufficient=result["data_sufficient"],
        insufficiency_reasons=result["insufficiency_reasons"], estimated_coverage=result["estimated_coverage"],
        estimated_referral_rate=result["estimated_referral_rate"],
        historical_false_resolution_rate=result["historical_false_resolution_rate"],
        confidence_interval_low=result["confidence_interval"][0] if result["confidence_interval"] else None,
        confidence_interval_high=result["confidence_interval"][1] if result["confidence_interval"] else None,
        sensitive_category_override=result["sensitive_category_override"], based_on="ticket_decisions",
        created_by=user.id,
    )
    db.add(row)
    await db.flush()
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.threshold_simulation.created", resource_type="threshold_simulation", resource_id=str(row.id), metadata_json={"proposed_threshold": payload.proposed_threshold, "sample_size": result["sample_size"], "data_sufficient": result["data_sufficient"]}))
    await db.commit(); await db.refresh(row)
    return simulation_json(row)


@router.get("/simulations")
async def list_simulations(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "threshold:read")
    await require_flag_enabled(db, user)
    total = int(await db.scalar(select(func.count()).select_from(ThresholdSimulation).where(ThresholdSimulation.tenant_id == user.tenant_id)) or 0)
    rows = (await db.scalars(select(ThresholdSimulation).where(ThresholdSimulation.tenant_id == user.tenant_id).order_by(ThresholdSimulation.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [simulation_json(row) for row in rows], "page": page, "page_size": page_size, "total": total}
