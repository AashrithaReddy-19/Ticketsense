"""Transactional, backend-controlled ticket and response-draft lifecycle."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import canonical_role, has_permission
from app.models.platform import AuditLog
from app.models.feedback import Feedback
from app.models.response_draft import EngineerDepartment, EngineerSpecialization, ResponseDraft, TicketEvent
from app.models.enterprise import AssignmentDecision, EngineerProfile, EngineerSkill
from app.models.ai_draft import AIDraft
from app.models.ai_pipeline import ClaimValidation
from app.models.ticket import Ticket
from app.models.ticket_history import TicketHistory
from app.models.user import User


PUBLIC_MESSAGES = {
    "submitted": "Your ticket has been received.",
    "needs_clarification": "More information is needed before analysis can continue.",
    "ai_processing": "TicketSense is securely analyzing your ticket.",
    "awaiting_assignment": "Your ticket is waiting for the most suitable support engineer.",
    "processing": "Your ticket is being processed.",
    "classified": "Your ticket has been classified.",
    "routed": "Your ticket has been assigned to the appropriate support team.",
    "assigned": "A support engineer has been assigned to your ticket.",
    "in_progress": "A support engineer is working on your request.",
    "awaiting_customer": "Support is waiting for your reply.",
    "pending_review": "The proposed resolution is being reviewed.",
    "changes_requested": "A support engineer is working on your request.",
    "approved": "A reviewed resolution has been approved.",
    "resolved": "A reviewed resolution has been provided.",
    "resolved_by_ai": "A verified AI resolution is ready for your confirmation.",
    "resolved_by_engineer": "A support engineer has provided a resolution.",
    "escalated": "Your ticket has been escalated to a specialist.",
    "reopened": "Your ticket has been reopened.",
    "closed": "Your ticket has been closed.",
    "ai_processing_failed": "Automated analysis could not finish; your ticket requires human support.",
}

ALLOWED_TRANSITIONS = {
    "submitted": {"needs_clarification", "ai_processing", "processing", "routed", "awaiting_assignment", "escalated"},
    "needs_clarification": {"ai_processing", "awaiting_assignment", "closed"},
    "ai_processing": {"resolved_by_ai", "awaiting_assignment", "assigned", "ai_processing_failed", "escalated"},
    "awaiting_assignment": {"assigned", "escalated", "closed"},
    "processing": {"classified", "escalated"},
    "classified": {"routed", "escalated"},
    "routed": {"awaiting_assignment", "assigned", "resolved_by_ai", "escalated"},
    "assigned": {"in_progress", "resolved_by_ai", "escalated"},
    "in_progress": {"awaiting_customer", "resolved_by_engineer", "pending_review", "escalated"},
    "awaiting_customer": {"in_progress", "resolved_by_engineer", "escalated", "closed"},
    "pending_review": {"changes_requested", "approved", "escalated"},
    "changes_requested": {"in_progress", "pending_review", "escalated"},
    "approved": {"resolved"},
    "resolved": {"reopened", "closed"},
    "resolved_by_ai": {"reopened", "closed"},
    "resolved_by_engineer": {"reopened", "closed"},
    "reopened": {"awaiting_assignment", "assigned", "in_progress", "escalated"},
    "ai_processing_failed": {"ai_processing", "awaiting_assignment", "assigned", "escalated", "closed"},
    "escalated": {"assigned", "in_progress", "closed"},
    "closed": {"reopened"},
}


def ensure_transition(old: str, new: str) -> None:
    if new not in ALLOWED_TRANSITIONS.get(old, set()):
        raise HTTPException(409, f"Invalid ticket transition: {old} -> {new}")


async def locked_ticket(db: AsyncSession, ticket_id: UUID, tenant_id: UUID) -> Ticket:
    ticket = await db.scalar(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id, Ticket.deleted_at.is_(None)).with_for_update())
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


def record_event(db: AsyncSession, ticket: Ticket, user: User | None, event_type: str, old_status: str | None, new_status: str | None, comment: str | None = None, draft_version: int | None = None, visibility: str = "internal", old_assignee_id: UUID | None = None, new_assignee_id: UUID | None = None, metadata: dict | None = None, correlation_id: UUID | None = None) -> None:
    correlation_id = correlation_id or uuid4()
    db.add(TicketEvent(tenant_id=ticket.tenant_id, ticket_id=ticket.id, event_type=event_type, old_status=old_status, new_status=new_status, actor_id=user.id if user else None, actor_role=canonical_role(user.role) if user else "system", comment=comment, draft_version=draft_version, visibility=visibility, old_assignee_id=old_assignee_id, new_assignee_id=new_assignee_id, correlation_id=correlation_id, metadata_json=metadata or {}))
    db.add(TicketHistory(ticket_id=ticket.id, actor_id=user.id if user else None, action=event_type, detail={"old_status": old_status, "new_status": new_status, "comment": comment, "draft_version": draft_version, "visibility": visibility}))
    db.add(AuditLog(tenant_id=ticket.tenant_id, user_id=user.id if user else None, action=f"workflow.{event_type}", resource_type="ticket", resource_id=str(ticket.id), metadata_json={"old_status": old_status, "new_status": new_status, "draft_version": draft_version, "old_assignee_id": str(old_assignee_id) if old_assignee_id else None, "new_assignee_id": str(new_assignee_id) if new_assignee_id else None, "correlation_id": str(correlation_id), **(metadata or {})}))


def transition(db: AsyncSession, ticket: Ticket, user: User | None, new_status: str, event_type: str, comment: str | None = None, visibility: str = "both", draft_version: int | None = None) -> None:
    old = ticket.status
    ensure_transition(old, new_status)
    ticket.status = new_status
    ticket.public_status_message = PUBLIC_MESSAGES[new_status]
    record_event(db, ticket, user, event_type, old, new_status, comment, draft_version, visibility)


async def next_version(db: AsyncSession, ticket_id: UUID) -> int:
    return int((await db.scalar(select(func.max(ResponseDraft.version_number)).where(ResponseDraft.ticket_id == ticket_id))) or 0) + 1


async def create_draft(db: AsyncSession, ticket: Ticket, user: User, content: str, author_type: str, status: str, based_on: UUID | None = None, citations: list | None = None) -> ResponseDraft:
    if not content.strip():
        raise HTTPException(422, "Response content is required")
    previous = await db.get(ResponseDraft, ticket.latest_draft_id) if ticket.latest_draft_id else None
    if previous and previous.status not in {"approved", "rejected", "superseded"}:
        previous.status = "superseded"
    draft = ResponseDraft(tenant_id=ticket.tenant_id, ticket_id=ticket.id, version_number=await next_version(db, ticket.id), content=content.strip(), author_type=author_type, created_by_user_id=user.id, creator_role=canonical_role(user.role), based_on_draft_id=based_on or (previous.id if previous else None), citations=citations or [], status=status, confidence_score=float(ticket.confidence_score) if ticket.confidence_score is not None else None)
    db.add(draft)
    await db.flush()
    await validate_response_version(db, ticket, draft)
    ticket.latest_draft_id = draft.id
    ticket.ai_draft_reply = draft.content  # compatibility snapshot; never customer-visible
    return draft


async def validate_response_version(db: AsyncSession, ticket: Ticket, draft: ResponseDraft) -> None:
    """Persist an immutable validation snapshot for this response version.

    Older Release A tickets may not have a grounded AIDraft/evidence snapshot. In
    that case the version remains explicitly ``not_available`` and the established
    human workflow continues unchanged. When evidence exists, every new Engineer
    or Reviewer version is checked independently and linked claim rows are added.
    """
    ai_draft=await db.scalar(select(AIDraft).where(AIDraft.ticket_id==ticket.id,AIDraft.tenant_id==ticket.tenant_id))
    if not ai_draft or not ai_draft.evidence:
        draft.citation_validation_status="not_available"
        draft.validation_details={"status":"not_available","reason":"No grounded evidence snapshot exists for this ticket"}
        return
    import re
    from ai.graph.nodes import validate_citations_node
    from ai.agents.grounding import validate_grounding
    inline=sorted(set(re.findall(r"\[((?:KB|RT)-\d{3})\]",draft.content)))
    structured=draft.citations or [{"citation_id":citation_id} for citation_id in inline]
    state={"tenant_id":str(ticket.tenant_id),"department_id":str(ticket.department_id or ""),"article_version":ai_draft.article_version,
           "retrieved_chunks":ai_draft.evidence,"draft_reply":draft.content,"citations":structured,
           "generation_status":"generated","insufficient_evidence":False}
    citation=(await validate_citations_node(state))["citation_validation"]
    grounding=validate_grounding(draft.content,ai_draft.evidence,citation)
    draft.citations=structured
    draft.citation_validation_status="valid" if citation["valid"] else "invalid"
    draft.validation_details={"citation":citation,"grounding":grounding,"validator_version":grounding["validator_version"],"evidence_execution_id":(ai_draft.validation_details or {}).get("execution_id")}
    execution_id=(ai_draft.validation_details or {}).get("execution_id")
    if execution_id:
        for claim in grounding.get("claims",[]):
            db.add(ClaimValidation(tenant_id=ticket.tenant_id,ticket_id=ticket.id,execution_id=UUID(execution_id),response_draft_id=draft.id,**claim))


def ensure_response_ready(draft: ResponseDraft) -> None:
    details=draft.validation_details or {}
    if draft.citation_validation_status=="invalid" or details.get("grounding",{}).get("blocked"):
        raise HTTPException(409,"Response version is blocked by citation or grounding validation; correct it and save a new version")


async def assign_ticket(db: AsyncSession, ticket: Ticket, actor: User | None, engineer: User, comment: str | None = None, metadata: dict | None = None) -> None:
    if canonical_role(engineer.role) != "support_agent" or not engineer.is_active:
        raise HTTPException(422, "Active department engineer required")
    if engineer.tenant_id != ticket.tenant_id or engineer.department_id != ticket.department_id:
        raise HTTPException(409, "Engineer must belong to the ticket department")
    if ticket.assignee_id == engineer.id:
        return
    old_assignee = ticket.assignee_id
    ticket.assignee_id = engineer.id
    now = datetime.now(timezone.utc)
    ticket.assigned_at = now
    ticket.assignment_reason = comment
    engineer.last_assigned_at = now
    if ticket.status in {"routed", "awaiting_assignment", "reopened", "escalated", "ai_processing_failed"}:
        old_status = ticket.status
        ensure_transition(old_status, "assigned")
        ticket.status = "assigned"; ticket.public_status_message = PUBLIC_MESSAGES["assigned"]
        record_event(db, ticket, actor, "ticket_assigned", old_status, "assigned", comment, visibility="both", old_assignee_id=old_assignee, new_assignee_id=engineer.id, metadata=metadata)
    else:
        record_event(db, ticket, actor, "ticket_reassigned", ticket.status, ticket.status, comment, visibility="both", old_assignee_id=old_assignee, new_assignee_id=engineer.id, metadata=metadata)


def inferred_specialization(ticket: Ticket) -> str | None:
    text = f"{ticket.subject} {ticket.description}".lower()
    for term in ("vpn", "dns", "network", "cloud", "database", "sap", "hr"):
        if term in text: return term
    return None


async def auto_assign_ticket(db: AsyncSession, ticket: Ticket) -> User | None:
    """Deterministically rank authorized engineers by skill, capacity and fairness.

    The factor snapshot is persisted so an Admin can explain or override the
    decision. Missing Release-A profile rows degrade safely to the old user fields.
    """
    if ticket.assignee_id or not ticket.department_id or not ticket.tenant_id:
        return None
    candidates = (await db.scalars(
        select(User).join(EngineerDepartment, EngineerDepartment.user_id == User.id).where(
            User.tenant_id == ticket.tenant_id,
            EngineerDepartment.department_id == ticket.department_id,
            User.role.in_(("support_agent", "department_engineer")),
            User.is_active.is_(True), User.is_available.is_(True),
        ).order_by(User.last_assigned_at.asc().nullsfirst(), User.id).with_for_update()
    )).all()
    if not candidates: return None
    active_states = ("assigned", "in_progress", "awaiting_customer", "pending_review", "changes_requested", "reopened", "escalated")
    ranked = []
    desired = (ticket.required_specialization or inferred_specialization(ticket) or "general support").lower()
    priority_weight = {"low": .75, "medium": 1.0, "high": 1.5, "urgent": 2.0}
    level_score = {"none": 0.0, "basic": .25, "intermediate": .5, "advanced": .75, "expert": 1.0}
    for engineer in candidates:
        active_tickets = (await db.scalars(select(Ticket).where(Ticket.assignee_id == engineer.id, Ticket.status.in_(active_states), Ticket.deleted_at.is_(None)))).all()
        weighted_load = sum(float(row.complexity_weight or priority_weight.get(row.priority or "medium", 1.0)) for row in active_tickets)
        profile = await db.get(EngineerProfile, engineer.id)
        capacity = float(profile.max_weighted_capacity if profile else engineer.max_active_workload)
        availability = (profile.availability_status if profile else "available" if engineer.is_available else "offline")
        if availability != "available" or weighted_load >= capacity:
            continue
        skill_rows = (await db.scalars(select(EngineerSkill).where(EngineerSkill.user_id == engineer.id, EngineerSkill.department_id == ticket.department_id, EngineerSkill.is_active.is_(True)))).all()
        if skill_rows:
            matched = [row for row in skill_rows if desired in row.specialization.lower() or row.specialization.lower() in desired]
            skill = max((level_score.get(row.skill_level, 0.0) for row in matched), default=0.15)
            skill_label = max(matched, key=lambda row: level_score.get(row.skill_level, 0.0)).skill_level if matched else "department"
        else:
            names = [value.lower() for value in (await db.scalars(select(EngineerSpecialization.name).where(EngineerSpecialization.user_id == engineer.id, EngineerSpecialization.department_id == ticket.department_id))).all()]
            skill = .6 if any(desired in name or name in desired for name in names) else .15
            skill_label = "legacy specialization" if skill > .15 else "department"
        utilization = min(1.0, weighted_load / max(capacity, .1))
        headroom = 1.0 - utilization
        performance = profile.performance_snapshot if profile else {}
        success = float(performance.get("similar_category_success_rate", .5))
        escalation = float(performance.get("escalation_rate", .0))
        fairness = 1.0 if engineer.last_assigned_at is None else .5
        score = round(40*skill + 25*headroom + 15 + 10*success + 5*(1-escalation) + 5*fairness, 4)
        factors = {"skill_match": round(skill, 4), "skill_level": skill_label, "weighted_load": round(weighted_load, 2), "capacity": capacity, "capacity_headroom": round(headroom, 4), "availability": availability, "similar_category_success": success, "escalation_rate": escalation, "fairness": fairness, "required_specialization": desired}
        ranked.append((-score, weighted_load, engineer.last_assigned_at or datetime.min.replace(tzinfo=timezone.utc), str(engineer.id), engineer, factors))
    if not ranked: return None
    negative_score, weighted_load, _, _, selected, factors = min(ranked, key=lambda item: item[:4])
    score = -negative_score
    reason = f"Assigned to {selected.full_name}: {factors['skill_level']} match for {desired}, available, weighted workload {weighted_load:g}/{factors['capacity']:g}, deterministic score {score:.1f}."
    await assign_ticket(db, ticket, None, selected, reason, {"selection":"weighted_skill_capacity_fairness_v1", **factors, "score":score})
    db.add(AssignmentDecision(tenant_id=ticket.tenant_id,ticket_id=ticket.id,engineer_id=selected.id,decision_type="automatic",score=score,factor_breakdown=factors,explanation=reason))
    return selected


async def approve_draft(db: AsyncSession, ticket: Ticket, reviewer: User, draft: ResponseDraft, content: str | None, comment: str | None, modified: bool) -> ResponseDraft:
    if ticket.status != "pending_review":
        raise HTTPException(409, "Only a pending-review ticket can be approved")
    approved = draft
    if modified:
        approved = await create_draft(db, ticket, reviewer, content or "", "reviewer", "reviewer_modified", draft.id, draft.citations)
    elif content and content.strip() != draft.content:
        raise HTTPException(422, "Use modify_and_approve when response content changes")
    ensure_response_ready(approved)
    approved.status = "approved"
    approved.is_final = True
    transition(db, ticket, reviewer, "approved", "response_approved", comment, "internal", approved.version_number)
    now = datetime.now(timezone.utc)
    ticket.final_response = approved.content
    ticket.final_response_draft_id = approved.id
    ticket.final_responder_id = approved.created_by_user_id
    ticket.final_approver_id = reviewer.id
    ticket.approved_at = now
    text_change_ratio = None
    if modified:
        from ai.evaluation.metrics import character_error_rate
        text_change_ratio = character_error_rate(approved.content, draft.content)
    db.add(Feedback(
        ticket_id=ticket.id,
        reviewer_id=reviewer.id,
        action="edit" if modified else "accept",
        edited_reply=approved.content if modified else None,
        reject_reason=comment,
        text_change_ratio=text_change_ratio,
    ))
    transition(db, ticket, reviewer, "resolved", "ticket_resolved", "A reviewed resolution has been provided.", "both", approved.version_number)
    ticket.resolved_at = now
    from ai.embeddings.resolution_index import index_resolution
    await index_resolution(db, ticket)
    return approved
