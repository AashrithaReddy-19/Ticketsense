from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.core.rbac import canonical_role
from app.models.department import Department
from app.models.feedback import Feedback
from app.models.operations import PipelineMetric
from app.models.ticket import Ticket
from app.models.user import User

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

CONFIDENCE_BUCKETS = (("low", 0.0, 0.55), ("borderline", 0.55, 0.80), ("high", 0.80, 1.0001))


@router.get("")
async def analytics(user: User = Depends(require_role("support_agent", "manager", "enterprise_admin", "ai_admin", "department_engineer", "admin", "team_lead", "system_admin", "reviewer")), db: AsyncSession = Depends(get_db)):
    ticket_scope = [Ticket.tenant_id == user.tenant_id, Ticket.deleted_at.is_(None)]
    if canonical_role(user.role) in {"support_agent", "reviewer", "team_lead"}:
        ticket_scope.append(Ticket.department_id == user.department_id)

    rows = (await db.execute(select(Ticket.status, func.count()).where(*ticket_scope).group_by(Ticket.status))).all()
    counts = dict(rows); total = sum(counts.values())
    avg = await db.scalar(select(func.avg(Ticket.confidence_score)).where(*ticket_scope))

    # --- Human decision outcomes (Phase 12: AI acceptance/edit/rejection/escalation rates) ---
    decision_rows = (await db.execute(
        select(Feedback.action, func.count()).join(Ticket, Ticket.id == Feedback.ticket_id)
        .where(*ticket_scope).group_by(Feedback.action)
    )).all()
    decisions = dict(decision_rows); decided_total = sum(decisions.values())

    def rate(action: str) -> float | None:
        return round(decisions.get(action, 0) / decided_total, 4) if decided_total else None

    # --- Confidence distribution ---
    confidence_distribution = {}
    for label, low, high in CONFIDENCE_BUCKETS:
        confidence_distribution[label] = await db.scalar(
            select(func.count()).select_from(Ticket).where(
                *ticket_scope, Ticket.confidence_score >= low, Ticket.confidence_score < high,
            )
        ) or 0

    # --- Response/resolution timing ---
    avg_response_seconds = await db.scalar(select(func.avg(func.extract("epoch", Ticket.assigned_at - Ticket.created_at))).where(*ticket_scope, Ticket.assigned_at.is_not(None)))
    avg_resolution_seconds = await db.scalar(select(func.avg(func.extract("epoch", Ticket.resolved_at - Ticket.created_at))).where(*ticket_scope, Ticket.resolved_at.is_not(None)))

    # --- Department performance ---
    department_rows = (await db.execute(
        select(Department.id, Department.name, func.count(Ticket.id), func.avg(Ticket.confidence_score),
               func.count().filter(Ticket.status.in_(("resolved", "closed"))))
        .select_from(Department).outerjoin(Ticket, (Ticket.department_id == Department.id) & (Ticket.tenant_id == user.tenant_id))
        .where(Department.tenant_id == user.tenant_id,
               *([Department.id == user.department_id] if canonical_role(user.role) in {"support_agent", "reviewer", "team_lead"} else []))
        .group_by(Department.id, Department.name)
    )).all()
    department_performance = [
        {"department_id": did, "department": name, "total_tickets": tickets or 0,
         "resolved_tickets": resolved or 0, "average_confidence": round(float(conf), 4) if conf is not None else None}
        for did, name, tickets, conf, resolved in department_rows
    ]

    # --- Pipeline-stage latency (Phase 12 latency monitoring) ---
    stage_rows = (await db.execute(
        select(PipelineMetric.stage, func.avg(PipelineMetric.duration_ms), func.count(),
               func.count().filter(PipelineMetric.success.is_(False)))
        .outerjoin(Ticket, Ticket.id == PipelineMetric.ticket_id)
        .where(PipelineMetric.tenant_id == user.tenant_id,
               *([Ticket.department_id == user.department_id] if canonical_role(user.role) in {"support_agent", "reviewer", "team_lead"} else []))
        .group_by(PipelineMetric.stage)
    )).all()
    pipeline_stage_latency = [
        {"stage": stage, "average_duration_ms": round(float(avg_ms), 1) if avg_ms is not None else None,
         "sample_count": n, "failure_count": failures}
        for stage, avg_ms, n, failures in stage_rows
    ]

    return {
        "total_tickets": total,
        "open_tickets": sum(count for status, count in counts.items() if status not in {"resolved", "closed"}),
        "resolved_tickets": counts.get("resolved", 0) + counts.get("closed", 0),
        "escalated_tickets": counts.get("escalated", 0),
        "average_confidence": round(float(avg or 0), 2), "status_distribution": counts,
        # Additive Phase 12 fields — existing consumers of the fields above are unaffected.
        "ai_acceptance_rate": rate("accept"), "engineer_edit_rate": rate("edit"),
        "reviewer_modification_rate": rate("edit"), "rejection_rate": rate("reject"),
        "escalation_rate": rate("escalate"),
        "ai_human_agreement": round(decisions.get("accept", 0) / decided_total, 4) if decided_total else None,
        "confidence_distribution": confidence_distribution,
        "average_response_time_hours": round(float(avg_response_seconds) / 3600, 2) if avg_response_seconds is not None else None,
        "average_resolution_time_hours": round(float(avg_resolution_seconds) / 3600, 2) if avg_resolution_seconds is not None else None,
        "department_performance": department_performance,
        "pipeline_stage_latency": pipeline_stage_latency,
    }
