"""Three-experience enterprise APIs with capability and visibility enforcement."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import is_customer, public_role
from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.enterprise import (
    DepartmentResolutionPolicy, DiagnosticPlan, DiagnosticStep, EngineerProfile,
    EngineerSkill, ResolutionConfirmation, TicketDecision, TicketMessage,
    TicketMessageRead,
)
from app.models.platform import AuditLog, Notification
from app.models.ticket import Ticket
from app.models.user import User
from app.services.rag_pipeline import generate_and_store_draft
from app.services.resolution_policy import process_resolution_decision, serialize_decision
from app.services.sla import breach_risk
from app.services.ticket_visibility import get_visible_ticket, visible_ticket_query
from app.services.workflow import auto_assign_ticket, locked_ticket, record_event, transition
from app.config import settings
from ai.agents.llm_interface import get_llm_provider

router = APIRouter(prefix="/api", tags=["enterprise-platform"])


class TranslateRequest(BaseModel):
    target_language: str = Field(pattern="^(en|hi|te|ta)$")


async def run_translation(text: str, source_language: str, target_language: str) -> dict:
    try:
        result = await get_llm_provider(settings.llm_provider).translate(text, source_language, target_language)
    except Exception:
        from ai.agents.llm_interface import DeterministicDevelopmentProvider
        result = await DeterministicDevelopmentProvider().translate(text, source_language, target_language)
    return result.model_dump()


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    visibility: str = Field(default="public", pattern="^(public|internal)$")
    original_language: str = Field(default="en", pattern="^(en|hi|te|ta)$")
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=10)


class ConfirmationCreate(BaseModel):
    outcome: str = Field(pattern="^(solved|needs_help)$")
    reason: str | None = Field(default=None, max_length=2_000)


class DiagnosticStepCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    instruction: str = Field(min_length=3, max_length=4_000)
    safety_warning: str | None = Field(default=None, max_length=1_000)
    evidence_required: bool = False


class DiagnosticPlanCreate(BaseModel):
    summary: str | None = Field(default=None, max_length=2_000)
    steps: list[DiagnosticStepCreate] = Field(min_length=1, max_length=30)


class DiagnosticStepUpdate(BaseModel):
    status: str = Field(pattern="^(pending|passed|failed|not_applicable|requires_escalation)$")
    result_note: str | None = Field(default=None, max_length=2_000)


class ResolutionPolicyCreate(BaseModel):
    department_id: UUID | None = None
    category: str | None = Field(default=None, max_length=120)
    risk_class: str | None = Field(default=None, max_length=40)
    allow_auto_resolution: bool = False
    auto_resolve_threshold: float = Field(default=.85, ge=0, le=1)
    minimum_citation_coverage: float = Field(default=.8, ge=0, le=1)
    minimum_retrieval_score: float = Field(default=.65, ge=0, le=1)
    minimum_classification_confidence: float = Field(default=.75, ge=0, le=1)
    minimum_classification_margin: float = Field(default=.15, ge=0, le=1)
    auto_resolution_allowlist: list[str] = Field(default_factory=list, max_length=100)
    sensitive_category_denylist: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=3, max_length=1_000)


async def require_capability(db: AsyncSession, user: User, permission: str) -> None:
    if not await user_has_permission(db, user, permission):
        raise HTTPException(403, f"Permission required: {permission}")


@router.get("/experience")
async def experience(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(EngineerSkill).where(EngineerSkill.user_id == user.id, EngineerSkill.tenant_id == user.tenant_id, EngineerSkill.is_active.is_(True)))
    role = user.public_role or public_role(user.role)
    permissions = []
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    modules = ["overview", "tickets", "knowledge", "notifications"] if role == "customer" else ["command_center", "my_queue", "department_queue", "knowledge", "analytics"] if role == "engineer" else [
        module for capability, module in (
            ("ticket:read_all", "tickets"), ("user:manage", "engineers"), ("review:manage", "ai_review"),
            ("incident:manage", "incidents"), ("knowledge:manage", "knowledge"), ("analytics:all", "analytics"),
            ("audit:read", "audit"), ("integration:manage", "settings"),
        ) if capability in permissions
    ]
    return {"public_role": role, "internal_role": user.role, "landing_path": f"/{role}", "capabilities": permissions,
            "modules": modules, "skills": [{"specialization": row.specialization, "level": row.skill_level, "primary": row.is_primary} for row in rows]}


@router.post("/tickets/{ticket_id}/process")
async def process_ticket(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    visible = await get_visible_ticket(db, user, ticket_id)
    if is_customer(user.role) and visible.submitted_by != user.id:
        raise HTTPException(404, "Ticket not found")
    ticket = await locked_ticket(db, visible.id, user.tenant_id)
    existing = await db.scalar(select(TicketDecision).where(TicketDecision.ticket_id == ticket.id, TicketDecision.tenant_id == user.tenant_id).order_by(TicketDecision.created_at.desc()).limit(1))
    if existing and ticket.status in {"resolved_by_ai", "resolved_by_engineer", "closed"}:
        return {"ticket_id": ticket.id, "status": ticket.status, "public_status_message": ticket.public_status_message,
                "resolution_available": bool(ticket.final_response)} if is_customer(user.role) else serialize_decision(existing)
    if not ticket.department_id:
        ticket.status = "awaiting_assignment"
        record_event(db, ticket, None, "ai_processing_blocked", ticket.status, ticket.status, "Department routing is required", visibility="internal")
        await db.commit()
        return {"ticket_id": ticket.id, "status": ticket.status, "public_status_message": ticket.public_status_message}
    record_event(db, ticket, None, "ai_processing_started", ticket.status, ticket.status, "Grounded resolution workflow started", visibility="internal")
    draft = await generate_and_store_draft(db, ticket)
    if draft.generation_status not in {"ready", "generated"}:
        old = ticket.status
        ticket.status = "ai_processing_failed"
        ticket.public_status_message = "Automated analysis could not finish; a support engineer will continue."
        record_event(db, ticket, None, "ai_processing_failed", old, ticket.status, "A required validation or generation stage failed", visibility="both")
        await auto_assign_ticket(db, ticket)
        await db.commit()
        return {"ticket_id": ticket.id, "status": ticket.status, "public_status_message": ticket.public_status_message}
    decision = await process_resolution_decision(db, ticket, triggered_by=user.id)
    db.add(AuditLog(tenant_id=ticket.tenant_id, user_id=user.id, action="ticket.policy_decided", resource_type="ticket", resource_id=str(ticket.id), metadata_json={"decision": decision.decision, "reason_code": decision.reason_code}))
    await db.commit()
    await db.refresh(ticket)
    if is_customer(user.role):
        return {"ticket_id": ticket.id, "status": ticket.status, "public_status_message": ticket.public_status_message,
                "resolution_available": bool(ticket.final_response)}
    await db.refresh(decision)
    return serialize_decision(decision)


@router.get("/tickets/{ticket_id}/decision")
async def ticket_decision(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_capability(db, user, "ticket:internal_ai")
    ticket = await get_visible_ticket(db, user, ticket_id)
    decision = await db.scalar(select(TicketDecision).where(TicketDecision.ticket_id == ticket.id, TicketDecision.tenant_id == user.tenant_id).order_by(TicketDecision.created_at.desc()).limit(1))
    if not decision:
        raise HTTPException(404, "Policy decision is not available")
    return serialize_decision(decision)


def message_json(message: TicketMessage, author: User | None, read: bool) -> dict:
    return {"id": message.id, "ticket_id": message.ticket_id, "author_id": message.author_id,
        "author_name": author.full_name if author else "Former user", "visibility": message.visibility,
        "body": message.body, "original_language": message.original_language,
        "translated_body": message.translated_body, "translated_language": message.translated_language,
        "machine_translated": message.machine_translated, "attachment_ids": message.attachment_ids,
        "is_read": read, "created_at": message.created_at, "edited_at": message.edited_at}


@router.get("/tickets/{ticket_id}/messages")
async def messages(ticket_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await get_visible_ticket(db, user, ticket_id)
    query = select(TicketMessage).where(TicketMessage.ticket_id == ticket.id, TicketMessage.tenant_id == user.tenant_id)
    if is_customer(user.role):
        query = query.where(TicketMessage.visibility == "public")
    rows = (await db.scalars(query.order_by(TicketMessage.created_at).offset((page - 1) * page_size).limit(page_size))).all()
    result = []
    for row in rows:
        author = await db.get(User, row.author_id)
        read = bool(await db.scalar(select(TicketMessageRead).where(TicketMessageRead.message_id == row.id, TicketMessageRead.user_id == user.id)))
        result.append(message_json(row, author, read))
    return result


@router.post("/tickets/{ticket_id}/messages", status_code=201)
async def create_message(ticket_id: UUID, payload: MessageCreate, idempotency_key: str | None = Header(None, alias="Idempotency-Key"), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await get_visible_ticket(db, user, ticket_id)
    if payload.visibility == "internal":
        await require_capability(db, user, "message:internal")
    if is_customer(user.role) and payload.visibility != "public":
        raise HTTPException(403, "Customers can send public messages only")
    if idempotency_key:
        existing = await db.scalar(select(TicketMessage).where(TicketMessage.tenant_id == user.tenant_id, TicketMessage.idempotency_key == idempotency_key))
        if existing:
            author = await db.get(User, existing.author_id)
            return message_json(existing, author, True)
    message = TicketMessage(tenant_id=user.tenant_id, ticket_id=ticket.id, author_id=user.id,
        visibility=payload.visibility, body=payload.body.strip(), original_language=payload.original_language,
        attachment_ids=[str(item) for item in payload.attachment_ids], idempotency_key=idempotency_key)
    db.add(message)
    await db.flush()
    db.add(TicketMessageRead(message_id=message.id, user_id=user.id))
    if payload.visibility == "public":
        recipient = ticket.assignee_id if is_customer(user.role) else ticket.submitted_by
        if recipient:
            db.add(Notification(tenant_id=ticket.tenant_id, user_id=recipient, title="New ticket message", message=f"New public message on {ticket.subject}", kind="message"))
        if is_customer(user.role) and ticket.status == "awaiting_customer":
            transition(db, ticket, user, "in_progress", "customer_replied", "The customer supplied new information", "both")
    record_event(db, ticket, user, "public_message_added" if payload.visibility == "public" else "internal_note_added", ticket.status, ticket.status, None, visibility="both" if payload.visibility == "public" else "internal", metadata={"message_id": str(message.id)})
    await db.commit()
    await db.refresh(message)
    return message_json(message, user, True)


@router.post("/tickets/{ticket_id}/messages/{message_id}/read")
async def read_message(ticket_id: UUID, message_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await get_visible_ticket(db, user, ticket_id)
    message = await db.scalar(select(TicketMessage).where(TicketMessage.id == message_id, TicketMessage.ticket_id == ticket.id, TicketMessage.tenant_id == user.tenant_id))
    if not message or is_customer(user.role) and message.visibility != "public":
        raise HTTPException(404, "Message not found")
    existing = await db.scalar(select(TicketMessageRead).where(TicketMessageRead.message_id == message.id, TicketMessageRead.user_id == user.id))
    if not existing:
        db.add(TicketMessageRead(message_id=message.id, user_id=user.id))
        await db.commit()
    return {"message_id": message.id, "is_read": True}


@router.post("/tickets/{ticket_id}/messages/{message_id}/translate")
async def translate_message(ticket_id: UUID, message_id: UUID, payload: TranslateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await get_visible_ticket(db, user, ticket_id)
    message = await db.scalar(select(TicketMessage).where(TicketMessage.id == message_id, TicketMessage.ticket_id == ticket.id, TicketMessage.tenant_id == user.tenant_id))
    if not message or is_customer(user.role) and message.visibility != "public":
        raise HTTPException(404, "Message not found")
    result = await run_translation(message.body, message.original_language, payload.target_language)
    if result["available"]:
        message.translated_body = result["translated_text"]
        message.translated_language = payload.target_language
        message.machine_translated = result["machine_translated"]
        await db.commit()
    return {"message_id": message.id, **result}


@router.post("/tickets/{ticket_id}/resolution/translate")
async def translate_resolution(ticket_id: UUID, payload: TranslateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Translates the customer-safe final response on demand. Computed from the
    already-approved evidence-grounded text; never re-generates or re-approves
    an answer, and is not persisted — it is display-time translation only."""
    ticket = await get_visible_ticket(db, user, ticket_id)
    if is_customer(user.role) and ticket.submitted_by != user.id:
        raise HTTPException(404, "Ticket not found")
    if not ticket.final_response:
        raise HTTPException(409, "This ticket does not yet have a published resolution to translate")
    result = await run_translation(ticket.final_response, "en", payload.target_language)
    return {"ticket_id": ticket.id, **result}


@router.post("/tickets/{ticket_id}/resolution-confirmation")
async def confirm_resolution(ticket_id: UUID, payload: ConfirmationCreate, idempotency_key: str | None = Header(None, alias="Idempotency-Key"), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not is_customer(user.role):
        raise HTTPException(403, "Customer confirmation required")
    visible = await get_visible_ticket(db, user, ticket_id)
    ticket = await locked_ticket(db, visible.id, user.tenant_id)
    if idempotency_key:
        # Checked before the status guard: the transition this endpoint performs (resolved ->
        # closed/reopened) moves the ticket out of the very status this endpoint requires, so a
        # legitimate retry of an already-applied request must replay the original result rather
        # than fail on a status guard that the first call itself made no longer true.
        existing = await db.scalar(select(ResolutionConfirmation).where(ResolutionConfirmation.tenant_id == user.tenant_id, ResolutionConfirmation.idempotency_key == idempotency_key))
        if existing:
            return {"ticket_id": ticket.id, "status": ticket.status, "outcome": existing.outcome, "reopened_count": ticket.reopened_count}
    if ticket.status not in {"resolved", "resolved_by_ai", "resolved_by_engineer"}:
        raise HTTPException(409, "Only a resolved ticket can be confirmed")
    confirmation = ResolutionConfirmation(tenant_id=user.tenant_id, ticket_id=ticket.id, user_id=user.id,
        outcome=payload.outcome, reason=payload.reason, response_fingerprint=ticket.last_auto_resolution_fingerprint,
        idempotency_key=idempotency_key)
    db.add(confirmation)
    if payload.outcome == "solved":
        transition(db, ticket, user, "closed", "resolution_confirmed", payload.reason or "Customer confirmed the solution", "both")
    else:
        transition(db, ticket, user, "reopened", "resolution_rejected", payload.reason or "Customer still needs help", "both")
        ticket.reopened_count += 1
        ticket.auto_resolution_eligible = False
        ticket.auto_resolution_reason_code = "CUSTOMER_REJECTED_PREVIOUS_ANSWER"
        ticket.assignee_id = None
        await auto_assign_ticket(db, ticket)
    db.add(AuditLog(tenant_id=ticket.tenant_id, user_id=user.id, action=f"resolution.{payload.outcome}", resource_type="ticket", resource_id=str(ticket.id), metadata_json={"reopened_count": ticket.reopened_count}))
    await db.commit()
    await db.refresh(ticket)
    return {"ticket_id": ticket.id, "status": ticket.status, "outcome": payload.outcome, "reopened_count": ticket.reopened_count}


def plan_json(plan: DiagnosticPlan, steps: list[DiagnosticStep]) -> dict:
    return {"id": plan.id, "ticket_id": plan.ticket_id, "status": plan.status, "summary": plan.summary,
        "created_by": plan.created_by, "created_at": plan.created_at,
        "steps": [{"id": step.id, "sequence_number": step.sequence_number, "title": step.title,
            "instruction": step.instruction, "status": step.status, "safety_warning": step.safety_warning,
            "evidence_required": step.evidence_required, "result_note": step.result_note} for step in steps]}


@router.get("/tickets/{ticket_id}/diagnostic-plan")
async def diagnostic_plan(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_capability(db, user, "diagnostic:manage")
    ticket = await get_visible_ticket(db, user, ticket_id)
    plan = await db.scalar(select(DiagnosticPlan).where(DiagnosticPlan.ticket_id == ticket.id, DiagnosticPlan.tenant_id == user.tenant_id).order_by(DiagnosticPlan.created_at.desc()).limit(1))
    if not plan:
        raise HTTPException(404, "Diagnostic plan not found")
    steps = list((await db.scalars(select(DiagnosticStep).where(DiagnosticStep.plan_id == plan.id).order_by(DiagnosticStep.sequence_number))).all())
    return plan_json(plan, steps)


@router.post("/tickets/{ticket_id}/diagnostic-plan", status_code=201)
async def create_diagnostic_plan(ticket_id: UUID, payload: DiagnosticPlanCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_capability(db, user, "diagnostic:manage")
    ticket = await get_visible_ticket(db, user, ticket_id)
    if user.public_role == "engineer" and ticket.assignee_id != user.id:
        raise HTTPException(403, "Only the assigned Engineer can create a diagnostic plan")
    plan = DiagnosticPlan(tenant_id=user.tenant_id, ticket_id=ticket.id, created_by=user.id, summary=payload.summary)
    db.add(plan)
    await db.flush()
    steps = []
    for sequence, item in enumerate(payload.steps, 1):
        step = DiagnosticStep(plan_id=plan.id, sequence_number=sequence, title=item.title.strip(), instruction=item.instruction.strip(), safety_warning=item.safety_warning, evidence_required=item.evidence_required)
        db.add(step)
        steps.append(step)
    record_event(db, ticket, user, "diagnostic_plan_created", ticket.status, ticket.status, payload.summary, visibility="internal", metadata={"plan_id": str(plan.id), "step_count": len(steps)})
    await db.commit()
    for step in steps:
        await db.refresh(step)
    await db.refresh(plan)
    return plan_json(plan, steps)


@router.patch("/tickets/{ticket_id}/diagnostic-steps/{step_id}")
async def update_diagnostic_step(ticket_id: UUID, step_id: UUID, payload: DiagnosticStepUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_capability(db, user, "diagnostic:manage")
    ticket = await get_visible_ticket(db, user, ticket_id)
    step = await db.scalar(select(DiagnosticStep).join(DiagnosticPlan, DiagnosticPlan.id == DiagnosticStep.plan_id).where(DiagnosticStep.id == step_id, DiagnosticPlan.ticket_id == ticket.id, DiagnosticPlan.tenant_id == user.tenant_id))
    if not step:
        raise HTTPException(404, "Diagnostic step not found")
    step.status = payload.status
    step.result_note = payload.result_note
    record_event(db, ticket, user, "diagnostic_step_updated", ticket.status, ticket.status, payload.result_note, visibility="internal", metadata={"step_id": str(step.id), "status": step.status})
    await db.commit()
    return {"id": step.id, "status": step.status, "result_note": step.result_note}


@router.get("/admin/resolution-policies")
async def resolution_policies(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_capability(db, user, "policy:manage")
    rows = (await db.scalars(select(DepartmentResolutionPolicy).where(DepartmentResolutionPolicy.tenant_id == user.tenant_id).order_by(DepartmentResolutionPolicy.created_at.desc()))).all()
    return [{"id": row.id, "department_id": row.department_id, "category": row.category, "risk_class": row.risk_class,
        "version": row.version, "allow_auto_resolution": row.allow_auto_resolution,
        "auto_resolve_threshold": row.auto_resolve_threshold, "minimum_citation_coverage": row.minimum_citation_coverage,
        "minimum_retrieval_score": row.minimum_retrieval_score, "minimum_classification_confidence": row.minimum_classification_confidence,
        "minimum_classification_margin": row.minimum_classification_margin, "auto_resolution_allowlist": row.auto_resolution_allowlist,
        "sensitive_category_denylist": row.sensitive_category_denylist, "is_active": row.is_active, "reason": row.reason} for row in rows]


@router.post("/admin/resolution-policies", status_code=201)
async def create_resolution_policy(payload: ResolutionPolicyCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_capability(db, user, "policy:manage")
    if payload.department_id:
        from app.models.department import Department
        if not await db.scalar(select(Department).where(Department.id == payload.department_id, Department.tenant_id == user.tenant_id)):
            raise HTTPException(404, "Department not found")
    versions = await db.scalars(select(DepartmentResolutionPolicy.version).where(DepartmentResolutionPolicy.tenant_id == user.tenant_id, DepartmentResolutionPolicy.department_id == payload.department_id, DepartmentResolutionPolicy.category == payload.category, DepartmentResolutionPolicy.risk_class == payload.risk_class))
    version = max(list(versions), default=0) + 1
    policy = DepartmentResolutionPolicy(tenant_id=user.tenant_id, version=version, updated_by=user.id, **payload.model_dump())
    db.add(policy)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="policy.resolution_created", resource_type="department_resolution_policy", resource_id=str(policy.id), metadata_json={"version": version, "allow_auto_resolution": payload.allow_auto_resolution}))
    await db.commit()
    await db.refresh(policy)
    return {"id": policy.id, "version": policy.version, "allow_auto_resolution": policy.allow_auto_resolution}


@router.get("/dashboards/{experience_name}")
async def experience_dashboard(experience_name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    expected = user.public_role or public_role(user.role)
    if experience_name != expected:
        raise HTTPException(403, "This dashboard does not belong to your public experience")
    query = visible_ticket_query(user)
    tickets = list((await db.scalars(query)).all())
    counts = {}
    for ticket in tickets:
        counts[ticket.status] = counts.get(ticket.status, 0) + 1
    payload = {"experience": expected, "total_tickets": len(tickets), "status_counts": counts,
        "open_tickets": sum(count for status, count in counts.items() if status not in {"resolved", "resolved_by_ai", "resolved_by_engineer", "closed"}),
        "last_updated_at": datetime.now(timezone.utc), "metrics_source": "live_tenant_scoped_database"}
    if expected == "admin":
        await require_capability(db, user, "analytics:all")
        payload["resolved_by_ai"] = counts.get("resolved_by_ai", 0)
        payload["resolved_by_engineer"] = counts.get("resolved_by_engineer", 0) + counts.get("resolved", 0)
        payload["needs_assignment"] = counts.get("awaiting_assignment", 0)
        payload["failed_ai_processing"] = counts.get("ai_processing_failed", 0)
        open_states = {"resolved", "resolved_by_ai", "resolved_by_engineer", "closed"}
        payload["sla_at_risk"] = sum(1 for ticket in tickets if ticket.status not in open_states and ticket.sla_due_at and breach_risk(ticket.sla_due_at, ticket.created_at)["status"] == "at_risk")
        payload["sla_breached"] = sum(1 for ticket in tickets if ticket.status not in open_states and ticket.sla_due_at and breach_risk(ticket.sla_due_at, ticket.created_at)["status"] == "breached")
    return payload
