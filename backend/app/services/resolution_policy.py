"""Fail-closed automatic-resolution policy and publication service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_draft import AIDraft
from app.models.ai_pipeline import PipelineExecution
from app.models.enterprise import ConfidenceComponent, DepartmentResolutionPolicy, TicketDecision
from app.models.platform import Notification
from app.models.response_draft import ResponseDraft
from app.models.ticket import Ticket
from app.models.ticket_attachment import TicketAttachment
from app.services.knowledge_conflicts.detector import blocking_article_ids
from app.services.passport import create_passport
from app.services.playbooks import match_playbook, normalize_category, playbook_gate, record_recommendation
from app.services.workflow import PUBLIC_MESSAGES, auto_assign_ticket, next_version, record_event, transition


SENSITIVE_TERMS = {
    "payment", "billing", "credit card", "security", "breach", "credential", "password",
    "access control", "permission change", "data loss", "delete", "legal", "compliance",
}


@dataclass(frozen=True)
class Gate:
    code: str
    passed: bool
    score: float | None = None
    threshold: float | None = None
    detail: str = ""



async def applicable_policy(db: AsyncSession, ticket: Ticket, category: str) -> DepartmentResolutionPolicy | None:
    policies = list((await db.scalars(
        select(DepartmentResolutionPolicy).where(
            DepartmentResolutionPolicy.tenant_id == ticket.tenant_id,
            DepartmentResolutionPolicy.is_active.is_(True),
        ).order_by(DepartmentResolutionPolicy.version.desc())
    )).all())
    eligible = [p for p in policies if p.department_id in (None, ticket.department_id) and p.category in (None, category)]
    if not eligible:
        return None
    return max(eligible, key=lambda p: (p.department_id is not None, p.category is not None, p.risk_class is not None, p.version))


async def evaluate_resolution_gates(db: AsyncSession, ticket: Ticket, draft: AIDraft) -> tuple[DepartmentResolutionPolicy | None, str, list[Gate], str]:
    category = normalize_category(ticket)
    policy = await applicable_policy(db, ticket, category)
    threshold = float(policy.auto_resolve_threshold) if policy else .85
    validation = draft.validation_details or {}
    features = validation.get("confidence_features", {})
    citation = validation
    grounding = validation.get("grounding", {})
    evidence = draft.evidence or []
    analysis = (ticket.confidence_features or {}).get("analysis", {})
    text = f"{category} {ticket.subject} {ticket.description}".lower()
    sensitive = any(term in text for term in SENSITIVE_TERMS)
    denied = set(value.lower() for value in (policy.sensitive_category_denylist if policy else []))
    allowlist = set(value.lower() for value in (policy.auto_resolution_allowlist if policy else []))
    approved_evidence = [item for item in evidence if str(item.get("tenant_id")) == str(ticket.tenant_id)
                         and str(item.get("department_id")) == str(ticket.department_id)
                         and item.get("status") == "approved" and item.get("is_publishable") is True
                         and item.get("article_version") == draft.article_version and str(item.get("chunk_text", "")).strip()]
    retrieval = max((float(item.get("similarity", 0)) for item in approved_evidence), default=0.0)
    cited_article_ids = [item.get("article_id") for item in approved_evidence if item.get("article_id")]
    conflicted_article_ids = await blocking_article_ids(db, ticket.tenant_id, cited_article_ids)
    attachment = await db.scalar(select(TicketAttachment).where(TicketAttachment.ticket_id == ticket.id, TicketAttachment.tenant_id == ticket.tenant_id))
    ocr_ok = not attachment or attachment.extraction_status == "ready" and (not attachment.ocr_confidence_available or float(attachment.ocr_confidence or 0) >= .6)
    execution = await db.scalar(select(PipelineExecution).where(PipelineExecution.ticket_id == ticket.id, PipelineExecution.tenant_id == ticket.tenant_id).order_by(PipelineExecution.created_at.desc()).limit(1))
    overall = float(validation.get("confidence_score", ticket.confidence_score or 0))
    classification = float(features.get("classification_probability", 0))
    margin = float(features.get("classification_margin", 0))
    coverage = float(citation.get("citation_coverage", 0))
    min_classification = float(policy.minimum_classification_confidence) if policy else .75
    min_margin = float(policy.minimum_classification_margin) if policy else .15
    min_retrieval = float(policy.minimum_retrieval_score) if policy else .65
    min_coverage = float(policy.minimum_citation_coverage) if policy else .8
    fingerprint = sha256((draft.draft_text or "").strip().encode("utf-8")).hexdigest() if draft.draft_text else ""
    matched_playbook = await match_playbook(db, ticket, category=category)
    if matched_playbook is not None:
        await record_recommendation(db, ticket, matched_playbook)
    playbook_passed, playbook_detail = playbook_gate(matched_playbook)
    gates = [
        Gate("policy_enabled", bool(policy and policy.allow_auto_resolution), detail="A versioned policy explicitly enables automatic resolution"),
        Gate("category_allowlisted", category in allowlist, detail=f"Category is {category}"),
        Gate("category_not_sensitive", not sensitive and category not in denied, detail="Sensitive categories always require a human"),
        Gate("not_critical", ticket.priority != "urgent", detail=f"Priority is {ticket.priority}"),
        Gate("overall_confidence", overall >= threshold, overall, threshold, "Independent calibrated or deterministic confidence"),
        Gate("classification_confidence", classification >= min_classification, classification, min_classification),
        Gate("classification_margin", margin >= min_margin, margin, min_margin),
        Gate("approved_current_evidence", len(approved_evidence) > 0, float(len(approved_evidence)), 1.0),
        Gate("retrieval_relevance", retrieval >= min_retrieval, retrieval, min_retrieval),
        Gate("citation_validation", draft.citation_validation_status == "valid" and bool(citation.get("valid")), detail="Every citation identifier and scope must validate"),
        Gate("citation_coverage", coverage >= min_coverage, coverage, min_coverage),
        Gate("claim_grounding", not bool(grounding.get("blocked", True)) and grounding.get("overall_status") == "Grounded", detail=str(grounding.get("overall_status", "unavailable"))),
        Gate("no_contradiction", grounding.get("overall_status") != "Conflicting Evidence", detail="Contradiction validator"),
        Gate("pii_secrets", not bool(analysis.get("pii_detected")), detail="Detected secrets or personal data require human review"),
        Gate("attachment_quality", ocr_ok, score=float(attachment.ocr_confidence) if attachment and attachment.ocr_confidence is not None else None, threshold=.6 if attachment and attachment.ocr_confidence_available else None),
        Gate("pipeline_complete", bool(execution and execution.status in {"completed", "completed_with_fallback"}) and draft.generation_status == "ready", detail=f"Pipeline status: {execution.status if execution else 'missing'}"),
        Gate("immutable_response_available", bool(draft.draft_text and draft.citations), detail="A cited draft must exist before publication"),
        Gate("playbook_compatible", playbook_passed, detail=playbook_detail),
        Gate("no_immediate_repeat", not bool(fingerprint and fingerprint == ticket.last_auto_resolution_fingerprint), detail="A rejected answer cannot immediately auto-publish again"),
        Gate("no_unresolved_knowledge_conflict", not bool(conflicted_article_ids), detail="An open, high-severity knowledge conflict blocks cited evidence until an Admin reviews it" if conflicted_article_ids else "No unresolved high-severity conflict affects the cited evidence"),
    ]
    return policy, category, gates, fingerprint


async def process_resolution_decision(db: AsyncSession, ticket: Ticket, triggered_by: UUID | None = None) -> TicketDecision:
    draft = await db.scalar(select(AIDraft).where(AIDraft.ticket_id == ticket.id, AIDraft.tenant_id == ticket.tenant_id))
    if not draft:
        raise ValueError("A grounded draft is required before policy evaluation")
    policy, category, gates, fingerprint = await evaluate_resolution_gates(db, ticket, draft)
    passed = [gate.code for gate in gates if gate.passed]
    failed = [gate.code for gate in gates if not gate.passed]
    threshold = float(policy.auto_resolve_threshold) if policy else .85
    overall = float((draft.validation_details or {}).get("confidence_score", ticket.confidence_score or 0))
    execution_id = (draft.validation_details or {}).get("execution_id")
    execution_uuid = UUID(execution_id) if execution_id else None
    if not failed:
        decision_name, reason_code = "auto_resolve", "ALL_SAFETY_GATES_PASSED"
        explanation = f"Automatic resolution approved: all {len(gates)} gates passed at {overall:.1%} confidence against the {threshold:.1%} policy threshold."
    else:
        decision_name, reason_code = "assign_engineer", "SAFETY_GATES_FAILED"
        explanation = f"Human assistance required because {', '.join(failed)} did not pass."
    decision = TicketDecision(tenant_id=ticket.tenant_id, ticket_id=ticket.id, pipeline_execution_id=execution_uuid,
        policy_id=policy.id if policy else None, decision=decision_name, reason_code=reason_code,
        explanation=explanation, overall_confidence=overall, applicable_threshold=threshold,
        passed_gates=passed, failed_gates=failed, factors={gate.code: {"score": gate.score, "threshold": gate.threshold, "detail": gate.detail} for gate in gates},
        response_fingerprint=fingerprint or None)
    db.add(decision)
    await db.flush()
    for gate in gates:
        db.add(ConfidenceComponent(ticket_decision_id=decision.id, component=gate.code, score=gate.score, passed=gate.passed, threshold=gate.threshold, detail=gate.detail[:500] if gate.detail else None))
    ticket.category = category
    ticket.auto_resolution_eligible = not failed
    ticket.auto_resolution_reason_code = reason_code
    if not failed:
        version = await next_version(db, ticket.id)
        response = ResponseDraft(tenant_id=ticket.tenant_id, ticket_id=ticket.id, version_number=version,
            content=draft.draft_text.strip(), author_type="ai", creator_role="system", citations=draft.citations,
            status="approved", confidence_score=overall, citation_validation_status="valid",
            validation_details=draft.validation_details, is_final=True)
        db.add(response)
        await db.flush()
        ticket.latest_draft_id = response.id
        ticket.final_response_draft_id = response.id
        ticket.final_response = response.content
        ticket.resolution_type = "ai"
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.approved_at = ticket.resolved_at
        ticket.last_auto_resolution_fingerprint = fingerprint
        ticket.assignee_id = None
        transition(db, ticket, None, "resolved_by_ai", "ticket_auto_resolved", explanation, "both", version)
        db.add(Notification(tenant_id=ticket.tenant_id, user_id=ticket.submitted_by, title="AI resolution ready",
            message="A safety-checked resolution is ready. Please confirm whether it solved your issue.", kind="resolution"))
        await create_passport(db, ticket, response, resolution_type="ai", created_by=triggered_by or ticket.submitted_by, decision=decision)
    else:
        if not ticket.assignee_id:
            if ticket.status not in {"awaiting_assignment", "routed", "reopened", "escalated", "ai_processing_failed"}:
                transition(db, ticket, None, "awaiting_assignment", "human_assistance_required", explanation, "both")
            engineer = await auto_assign_ticket(db, ticket)
            if engineer is None:
                ticket.status = "awaiting_assignment"
                ticket.public_status_message = PUBLIC_MESSAGES["awaiting_assignment"]
                decision.decision = "admin_intervention"
                decision.reason_code = "NO_ELIGIBLE_ENGINEER"
                decision.explanation += " No authorized available Engineer has sufficient capacity; Admin intervention is required."
                record_event(db, ticket, None, "admin_intervention_required", ticket.status, ticket.status, decision.explanation, visibility="internal")
    return decision


def serialize_decision(decision: TicketDecision) -> dict:
    return {"id": decision.id, "ticket_id": decision.ticket_id, "decision": decision.decision,
        "reason_code": decision.reason_code, "explanation": decision.explanation,
        "overall_confidence": decision.overall_confidence, "applicable_threshold": decision.applicable_threshold,
        "passed_gates": decision.passed_gates, "failed_gates": decision.failed_gates,
        "factors": decision.factors, "created_at": decision.created_at}
