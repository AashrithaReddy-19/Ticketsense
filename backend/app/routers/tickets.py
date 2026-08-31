from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.ticket import Ticket
from app.models.platform import AIDecision, AuditLog, Notification
from app.models.ticket_history import TicketHistory
from app.models.feedback import Feedback
from app.models.user import User
from app.schemas.tickets import TicketAction, TicketCreate, TicketPublic
from app.services.ticket_intelligence import analyze_ticket
from app.services.ticket_visibility import get_visible_ticket, visible_ticket_query
from app.models.department import Department
from app.core.rbac import has_permission, is_customer

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def serialize(ticket: Ticket, user: User) -> TicketPublic:
    features = ticket.confidence_features or {}
    internal = has_permission(user.role, "ticket:internal_ai")
    return TicketPublic(
        id=ticket.id, subject=ticket.subject, description=ticket.description, status=ticket.status,
        priority=ticket.priority, sentiment=ticket.sentiment, department_id=ticket.department_id,
        ai_draft_reply=ticket.ai_draft_reply if internal else None,
        confidence_score=float(ticket.confidence_score) if internal and ticket.confidence_score is not None else None,
        analysis=features.get("analysis", {}) if internal else {}, created_at=ticket.created_at, updated_at=ticket.updated_at,
    )


async def scoped_ticket(ticket_id, user: User, db: AsyncSession) -> Ticket:
    try:
        resolved_id = UUID(str(ticket_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return await get_visible_ticket(db,user,resolved_id)


def require_internal_ticket_access(user: User) -> None:
    if not has_permission(user.role, "ticket:internal_ai"):
        raise HTTPException(status_code=403, detail="Internal AI analysis is not available for this role")


@router.post("", response_model=TicketPublic, status_code=status.HTTP_201_CREATED)
async def create_ticket(payload: TicketCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    analysis = await analyze_ticket(db, payload.subject, payload.description, user.department_id)
    category=str(analysis.get("category","")).lower(); department=None
    mapping={"network":"Networking","vpn":"Networking","cloud":"Cloud","hr":"HR","sap":"SAP"}
    for key,name in mapping.items():
        if key in category or key in f"{payload.subject} {payload.description}".lower():
            department=await db.scalar(select(Department).where(Department.tenant_id==user.tenant_id,Department.name==name)); break
    review=analysis["decision"]!="auto_resolve"
    ticket = Ticket(tenant_id=user.tenant_id, submitted_by=user.id, department_id=department.id if department else None, subject=payload.subject,
        description=payload.description, priority="urgent" if analysis["priority_score"] >= 90 else "high" if analysis["priority_score"] >= 70 else "medium",
        sentiment=analysis["sentiment"], status="escalated" if analysis["decision"] == "escalate" else "in_review",
        ai_draft_reply=analysis["draft"], confidence_score=analysis["confidence"], confidence_features={"analysis": analysis, "input": payload.model_dump()},review_required=review,review_reason="AI result requires human validation" if review else None,routing_state="routed" if department else "manual_triage")
    db.add(ticket); await db.flush()
    if user.tenant_id:
        for agent_name in ("ticket_understanding", "classification", "priority", "sla", "duplicate_detection", "knowledge_retrieval", "historical_ticket", "solution_generation", "root_cause", "evidence_validation", "policy_validation", "safety", "pii", "confidence", "routing", "knowledge_gap", "incident_detection", "knowledge_article", "feedback"):
            db.add(AIDecision(tenant_id=user.tenant_id, ticket_id=ticket.id, agent_name=agent_name, decision={"result": analysis.get("decision"), "category": analysis.get("category")}, confidence=analysis["confidence"], latency_ms=12))
        db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="ticket.created", resource_type="ticket", resource_id=str(ticket.id), metadata_json={"priority": ticket.priority}))
        db.add(Notification(tenant_id=user.tenant_id, user_id=user.id, title="Ticket analysis complete", message=f"{ticket.subject} is ready for {analysis['decision'].replace('_', ' ')}.", kind="ai"))
    for action, detail in (("ticket_created", {}), ("ai_analysis_completed", {"decision": analysis["decision"], "confidence": analysis["confidence"]})):
        db.add(TicketHistory(ticket_id=ticket.id, actor_id=user.id if action == "ticket_created" else None, action=action, detail=detail))
    await db.commit(); await db.refresh(ticket)
    return serialize(ticket, user)


@router.get("", response_model=list[TicketPublic])
async def list_tickets(q: str = "", status_filter: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = visible_ticket_query(user).order_by(Ticket.created_at.desc())
    if q:
        query = query.where(or_(Ticket.subject.ilike(f"%{q}%"), Ticket.description.ilike(f"%{q}%")))
    if status_filter:
        query = query.where(Ticket.status == status_filter)
    return [serialize(t, user) for t in (await db.scalars(query)).all()]


@router.get("/{ticket_id}", response_model=TicketPublic)
async def get_ticket(ticket_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return serialize(await scoped_ticket(ticket_id, user, db), user)


@router.post("/{ticket_id}/action", response_model=TicketPublic)
async def ticket_action(ticket_id: str, payload: TicketAction, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if is_customer(user.role) and payload.action not in {"reopen"}:
        raise HTTPException(status_code=403, detail="Support role required")
    ticket = await scoped_ticket(ticket_id, user, db)
    mapping = {"accept": "resolved", "resolve": "resolved", "edit": "resolved", "reject": "escalated", "escalate": "escalated", "reopen": "open"}
    if payload.action not in mapping: raise HTTPException(status_code=422, detail="Unsupported action")
    ticket.status = mapping[payload.action]
    if payload.response: ticket.ai_draft_reply = payload.response
    db.add(TicketHistory(ticket_id=ticket.id, actor_id=user.id, action=payload.action, detail={"reason": payload.reason}))
    await db.commit(); await db.refresh(ticket)
    return serialize(ticket, user)


@router.get("/{ticket_id}/trace")
async def trace(ticket_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_internal_ticket_access(user)
    ticket = await scoped_ticket(ticket_id, user, db)
    events = (await db.scalars(select(TicketHistory).where(TicketHistory.ticket_id == ticket.id).order_by(TicketHistory.created_at))).all()
    return [{"action": e.action, "detail": e.detail, "timestamp": e.created_at} for e in events]


@router.get("/{ticket_id}/ai-analysis")
async def ai_analysis(ticket_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_internal_ticket_access(user)
    return serialize(await scoped_ticket(ticket_id, user, db), user).analysis


@router.get("/{ticket_id}/evidence")
async def evidence(ticket_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_internal_ticket_access(user)
    ticket = await scoped_ticket(ticket_id, user, db)
    return (ticket.confidence_features or {}).get("analysis", {}).get("evidence", [])


@router.get("/{ticket_id}/similar")
async def similar(ticket_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_internal_ticket_access(user)
    ticket = await scoped_ticket(ticket_id, user, db)
    candidates = (await db.scalars(select(Ticket).where(Ticket.tenant_id == user.tenant_id, Ticket.id != ticket.id).limit(100))).all()
    words = set(ticket.subject.lower().split())
    ranked = sorted(((len(words & set(x.subject.lower().split())) / max(1, len(words | set(x.subject.lower().split()))), x) for x in candidates), reverse=True, key=lambda p:p[0])[:5]
    return [{"id": x.id, "subject": x.subject, "status": x.status, "similarity": round(score, 2), "resolution": x.ai_draft_reply} for score,x in ranked if score > 0]


@router.post("/{ticket_id}/feedback")
async def feedback(ticket_id: str, payload: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await scoped_ticket(ticket_id, user, db)
    rating = int(payload.get("rating", 0))
    if rating not in range(1, 6): raise HTTPException(422, "Rating must be between 1 and 5")
    db.add(Feedback(ticket_id=ticket.id, reviewer_id=user.id, action="accept" if payload.get("resolved", True) else "reject", reject_reason=payload.get("comment")))
    db.add(TicketHistory(ticket_id=ticket.id, actor_id=user.id, action="customer_feedback", detail={"rating": rating, "resolved": payload.get("resolved", True)}))
    await db.commit()
    return {"stored": True}
