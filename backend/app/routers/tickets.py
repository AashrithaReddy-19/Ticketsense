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
from app.schemas.tickets import DescriptionAssistRequest, DescriptionAssistResponse, TicketAction, TicketCreate, TicketPublic
from app.services.ticket_intelligence import analyze_ticket
from app.services.ticket_visibility import get_visible_ticket, visible_ticket_query
from app.models.department import Department
from app.core.rbac import has_permission, is_customer
from app.models.ai_draft import AIDraft
from app.models.response_draft import ResponseDraft, TicketEvent
from app.services.rag_pipeline import generate_and_store_draft, serialize_draft
from app.services.workflow import PUBLIC_MESSAGES, approve_draft, auto_assign_ticket, create_draft, locked_ticket, record_event, transition
from ai.agents.llm_interface import get_llm_provider
from app.config import settings
from app.services.confidence_gate import evaluate_confidence
from app.services.pipeline_metrics import StageTiming, persist_stage_timings, stage_timer
from app.services.sla import compute_sla_due_at
from collections import defaultdict, deque
from datetime import datetime, timezone
from uuid import uuid4
import time

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
_assist_windows: dict[str, deque[float]] = defaultdict(deque)


@router.post("/assist-description", response_model=DescriptionAssistResponse)
async def assist_description(payload: DescriptionAssistRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not has_permission(user.role, "ticket:create"):
        raise HTTPException(403, "Only customers can improve a ticket description")
    now = time.monotonic(); key = str(user.id); window = _assist_windows[key]
    while window and now - window[0] > 60: window.popleft()
    if len(window) >= 10: raise HTTPException(429, "Description assistant rate limit exceeded")
    window.append(now)
    original = " ".join(payload.description.replace("\x00", "").split()).strip()
    try:
        result = await get_llm_provider(settings.llm_provider).improve_description(payload.subject.strip(), original)
    except Exception:
        # A configured real LLM provider (Phase 14) can be unreachable, rate-limited or
        # misconfigured — the description assistant must never block ticket creation,
        # so any failure here falls back to the deterministic rule-based provider.
        from ai.agents.llm_interface import DeterministicDevelopmentProvider
        result = await DeterministicDevelopmentProvider().improve_description(payload.subject.strip(), original)
    db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="ticket.description_assisted",resource_type="ticket_draft",metadata_json={"provider":result.provider,"model":result.model}))
    await db.commit()
    return DescriptionAssistResponse(original=original,suggested=result.suggested,missing_information_questions=result.missing_information_questions,mode=f"{result.provider}:{result.model}")


def serialize(ticket: Ticket, user: User, department_name: str | None = None, final_responder_name: str | None = None) -> TicketPublic:
    features = ticket.confidence_features or {}
    internal = has_permission(user.role, "ticket:internal_ai")
    public_status = "in_progress" if is_customer(user.role) and ticket.status == "changes_requested" else ticket.status
    return TicketPublic(
        id=ticket.id, subject=ticket.subject, description=ticket.description, status=public_status,
        category=ticket.category, required_specialization=ticket.required_specialization if internal else None, resolution_type=ticket.resolution_type,
        priority=ticket.priority, sentiment=ticket.sentiment, department_id=ticket.department_id, department_name=department_name,
        assignee_id=ticket.assignee_id,
        ai_draft_reply=ticket.ai_draft_reply if internal else None,
        final_response=ticket.final_response,
        final_responder_name=final_responder_name,
        approved_at=ticket.approved_at, resolved_at=ticket.resolved_at,
        public_status_message=ticket.public_status_message or PUBLIC_MESSAGES.get(ticket.status),
        confidence_score=float(ticket.confidence_score) if internal and ticket.confidence_score is not None else None,
        analysis=features.get("analysis", {}) if internal else {}, sla_due_at=ticket.sla_due_at, reopened_count=ticket.reopened_count,
        created_at=ticket.created_at, updated_at=ticket.updated_at,
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
    trace_id = uuid4(); timings: list[StageTiming] = []; pipeline_started = time.monotonic()
    with stage_timer("classification", timings):
        analysis = await analyze_ticket(db, payload.subject, payload.description, user.department_id)
    category=str(analysis.get("category","")).lower(); department=None
    mapping={"payment":"Payments","billing":"Payments","network":"Networking","vpn":"Networking","cloud":"Cloud","hr":"HR","sap":"SAP"}
    with stage_timer("routing", timings):
        for key,name in mapping.items():
            if key in category or key in f"{payload.subject} {payload.description}".lower():
                department=await db.scalar(select(Department).where(Department.tenant_id==user.tenant_id,Department.name==name)); break
    with stage_timer("confidence_scoring", timings):
        confidence=await evaluate_confidence(db,user.tenant_id,department.id if department else None,analysis,payload.description)
    review=analysis["decision"]!="auto_resolve" or confidence["gate"]!="high"
    category = (payload.category or analysis.get("category") or "general_it").strip()
    specialization = next((name for term,name in (("vpn","VPN Engineer"),("payment","Payment Engineer"),("billing","Payment Engineer"),("sap","SAP Engineer"),("cloud","Cloud Engineer"),("hr","HR Systems Engineer"),("network","Network Engineer")) if term in f"{category} {payload.subject} {payload.description}".lower()), "General Support Engineer")
    ticket = Ticket(tenant_id=user.tenant_id, submitted_by=user.id, department_id=department.id if department else None, subject=payload.subject,
        description=payload.description, priority="urgent" if analysis["priority_score"] >= 90 else "high" if analysis["priority_score"] >= 70 else "medium",
        category=category, required_specialization=specialization, complexity_weight=2.0 if analysis["priority_score"] >= 90 else 1.5 if analysis["priority_score"] >= 70 else 1.0,
        sentiment=analysis["sentiment"], status="escalated" if analysis["decision"] == "escalate" else "routed" if department else "submitted",
        ai_draft_reply=analysis["draft"], confidence_score=confidence["score"], confidence_features={"analysis": analysis, "confidence_model":confidence, "input": payload.model_dump()},review_required=review,review_reason=f"Confidence gate: {confidence['gate']} ({confidence['model_version']})" if review else None,routing_state="routed" if department else "manual_triage")
    ticket.public_status_message = f"Your ticket has been assigned to the {department.name} team." if department else PUBLIC_MESSAGES["submitted"]
    db.add(ticket); await db.flush()
    if user.tenant_id:
        ticket.sla_due_at = await compute_sla_due_at(db, user.tenant_id, ticket.priority, ticket.created_at or datetime.now(timezone.utc))
    timings.append(StageTiming(stage="total_intake_pipeline", started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc), duration_ms=round((time.monotonic()-pipeline_started)*1000), success=True))
    persist_stage_timings(db, user.tenant_id, ticket.id, trace_id, timings)
    stages = [("ticket_submitted", None, "submitted", "both"), ("ai_processing_started", "submitted", "processing", "internal"), ("ticket_classified", "processing", "classified", "internal")]
    if department: stages.append(("ticket_routed", "classified", "routed", "both"))
    for event_type, old, new, visibility in stages:
        db.add(TicketEvent(tenant_id=ticket.tenant_id,ticket_id=ticket.id,event_type=event_type,old_status=old,new_status=new,actor_id=user.id if event_type=="ticket_submitted" else None,actor_role=user.role if event_type=="ticket_submitted" else "system",comment=PUBLIC_MESSAGES.get(new),visibility=visibility))
    if ticket.status == "routed":
        await auto_assign_ticket(db, ticket)
    if user.tenant_id:
        for agent_name in ("ticket_understanding", "classification", "priority", "sla", "duplicate_detection", "knowledge_retrieval", "historical_ticket", "solution_generation", "root_cause", "evidence_validation", "policy_validation", "safety", "pii", "confidence", "routing", "knowledge_gap", "incident_detection", "knowledge_article", "feedback"):
            db.add(AIDecision(tenant_id=user.tenant_id, ticket_id=ticket.id, agent_name=agent_name, decision={"result": analysis.get("decision"), "category": analysis.get("category"),"confidence_model_version":confidence["model_version"],"confidence_gate":confidence["gate"]}, confidence=confidence["score"], latency_ms=12))
        db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="ticket.created", resource_type="ticket", resource_id=str(ticket.id), metadata_json={"priority": ticket.priority}))
        db.add(Notification(tenant_id=user.tenant_id, user_id=user.id, title="Ticket analysis complete", message=f"{ticket.subject} is ready for {analysis['decision'].replace('_', ' ')}.", kind="ai"))
    for action, detail in (("ticket_created", {}), ("ai_analysis_completed", {"decision": analysis["decision"], "confidence": analysis["confidence"]})):
        db.add(TicketHistory(ticket_id=ticket.id, actor_id=user.id if action == "ticket_created" else None, action=action, detail=detail))
    await db.commit(); await db.refresh(ticket)
    return serialize(ticket, user, department.name if department else None)


@router.get("", response_model=list[TicketPublic])
async def list_tickets(q: str = "", status_filter: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = visible_ticket_query(user).order_by(Ticket.created_at.desc())
    if q:
        query = query.where(or_(Ticket.subject.ilike(f"%{q}%"), Ticket.description.ilike(f"%{q}%")))
    if status_filter:
        query = query.where(Ticket.status == status_filter)
    rows = (await db.scalars(query)).all(); result=[]
    for t in rows:
        department = await db.get(Department, t.department_id) if t.department_id else None
        responder = await db.get(User, t.final_responder_id) if t.final_responder_id else None
        result.append(serialize(t,user,department.name if department else None,responder.full_name if responder else None))
    return result


@router.get("/{ticket_id}", response_model=TicketPublic)
async def get_ticket(ticket_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket=await scoped_ticket(ticket_id,user,db); department=await db.get(Department,ticket.department_id) if ticket.department_id else None; responder=await db.get(User,ticket.final_responder_id) if ticket.final_responder_id else None
    return serialize(ticket,user,department.name if department else None,responder.full_name if responder else None)


@router.post("/{ticket_id}/action", response_model=TicketPublic)
async def ticket_action(ticket_id: str, payload: TicketAction, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if is_customer(user.role) and payload.action not in {"reopen"}:
        raise HTTPException(status_code=403, detail="Support role required")
    visible=await scoped_ticket(ticket_id,user,db); ticket=await locked_ticket(db,visible.id,user.tenant_id)
    if payload.action=="reopen":
        transition(db,ticket,user,"reopened","ticket_reopened",payload.reason,"both"); ticket.final_response=None; ticket.final_response_draft_id=None; ticket.approved_at=None; ticket.resolved_at=None
    elif payload.action=="escalate":
        if not has_permission(user.role,"ticket:escalate"): raise HTTPException(403,"Escalation permission required")
        transition(db,ticket,user,"escalated","ticket_escalated",payload.reason,"internal")
    elif payload.action=="reject":
        if not has_permission(user.role,"review:manage"): raise HTTPException(403,"Review permission required")
        transition(db,ticket,user,"changes_requested","review_rejected",payload.reason,"internal")
    elif payload.action in {"accept","resolve","edit"}:
        if not has_permission(user.role,"review:manage"): raise HTTPException(403,"Review permission required")
        if not payload.response: raise HTTPException(422,"A reviewed response is required")
        draft=await create_draft(db,ticket,user,payload.response,"reviewer","submitted_for_review")
        if ticket.status!="pending_review": raise HTTPException(409,"Ticket must be pending review")
        await approve_draft(db,ticket,user,draft,None,payload.reason,False); ticket.review_required=False
    else: raise HTTPException(status_code=422, detail="Unsupported action")
    await db.commit(); await db.refresh(ticket)
    department=await db.get(Department,ticket.department_id) if ticket.department_id else None; responder=await db.get(User,ticket.final_responder_id) if ticket.final_responder_id else None
    return serialize(ticket,user,department.name if department else None,responder.full_name if responder else None)


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


@router.get("/{ticket_id}/ai-draft")
async def get_ai_draft(ticket_id:str,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    require_internal_ticket_access(user); ticket=await scoped_ticket(ticket_id,user,db)
    draft=await db.scalar(select(AIDraft).where(AIDraft.ticket_id==ticket.id,AIDraft.tenant_id==user.tenant_id))
    if not draft: raise HTTPException(404,"Grounded draft has not been generated")
    return serialize_draft(draft)


@router.post("/{ticket_id}/ai-draft/generate")
async def generate_ai_draft(ticket_id:str,payload:dict|None=None,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    require_internal_ticket_access(user)
    if not (has_permission(user.role,"ticket:update") or has_permission(user.role,"review:manage")):
        raise HTTPException(403,"Draft regeneration is not allowed for this role")
    ticket=await scoped_ticket(ticket_id,user,db)
    if not ticket.tenant_id or not ticket.department_id: raise HTTPException(409,"Ticket must be tenant-scoped and routed before generation")
    draft=await generate_and_store_draft(db,ticket,(payload or {}).get("article_version","1.0"))
    db.add(TicketHistory(ticket_id=ticket.id,actor_id=user.id,action="grounded_draft_processed",detail={"status":draft.generation_status,"validation":draft.citation_validation_status}))
    await db.commit(); await db.refresh(draft); return serialize_draft(draft)


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
