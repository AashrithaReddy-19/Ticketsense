"""Resolution Passport creation and role-safe serialization.

``create_passport`` is called transactionally from inside the same resolution
flows that already exist (the fail-closed auto-resolution gate in
resolution_policy.py, and the human-engineer approval path in workflow.py) —
it never opens its own transaction or commits; the caller's existing commit
covers it, exactly like every other row those flows already write.
"""
import json
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_pipeline import ClaimValidation
from app.models.enterprise import ConfidenceComponent, ResolutionConfirmation, TicketDecision
from app.models.resolution_passport import ResolutionPassport
from app.models.response_draft import ResponseDraft
from app.models.ticket import Ticket

SCHEMA_VERSION = 1


def content_hash(text: str) -> str:
    return sha256((text or "").strip().encode("utf-8")).hexdigest()


def _integrity_hash(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _integrity_fields(passport: ResolutionPassport) -> dict:
    """The subset of a passport's own columns that its integrity_hash covers —
    everything immutable about the resolution itself. Deliberately excludes
    ``id``, ``created_at`` and ``integrity_hash`` (the row's own identity/
    hash), and ``is_current``/``supersedes_passport_id`` (bookkeeping that can
    legitimately change when a *later* passport supersedes this one, without
    that later event retroactively invalidating what this passport certified
    about the resolution that already happened)."""
    return {
        "schema_version": passport.schema_version, "tenant_id": str(passport.tenant_id),
        "department_id": str(passport.department_id) if passport.department_id else None,
        "ticket_id": str(passport.ticket_id), "resolution_type": passport.resolution_type,
        "input_content_hash": passport.input_content_hash, "classification_snapshot": passport.classification_snapshot,
        "pipeline_execution_id": str(passport.pipeline_execution_id) if passport.pipeline_execution_id else None,
        "ticket_decision_id": str(passport.ticket_decision_id) if passport.ticket_decision_id else None,
        "response_draft_id": str(passport.response_draft_id) if passport.response_draft_id else None,
        "response_version_number": passport.response_version_number, "response_content_hash": passport.response_content_hash,
        "citations": passport.citations, "claim_validations": passport.claim_validations,
        "confidence_components": passport.confidence_components,
        "overall_confidence": float(passport.overall_confidence) if passport.overall_confidence is not None else None,
        "applicable_threshold": float(passport.applicable_threshold) if passport.applicable_threshold is not None else None,
        "passed_gates": passport.passed_gates, "failed_gates": passport.failed_gates,
        "policy_id": str(passport.policy_id) if passport.policy_id else None, "policy_version": passport.policy_version,
        "engineer_edit_ratio": float(passport.engineer_edit_ratio) if passport.engineer_edit_ratio is not None else None,
        "feedback_id": str(passport.feedback_id) if passport.feedback_id else None,
        "reviewer_id": str(passport.reviewer_id) if passport.reviewer_id else None,
        "author_user_id": str(passport.author_user_id) if passport.author_user_id else None,
    }


def recompute_integrity_hash(passport: ResolutionPassport) -> str:
    return _integrity_hash(_integrity_fields(passport))


async def create_passport(
    db: AsyncSession, ticket: Ticket, response_draft: ResponseDraft, *, resolution_type: str,
    created_by, decision: TicketDecision | None = None, engineer_edit_ratio: float | None = None,
    feedback_id=None, reviewer_id=None, author_user_id=None, is_backfilled: bool = False,
) -> ResolutionPassport:
    if resolution_type not in ("ai", "engineer"):
        raise ValueError(f"Unknown resolution_type: {resolution_type}")

    claim_rows = (await db.scalars(select(ClaimValidation).where(ClaimValidation.response_draft_id == response_draft.id))).all()
    confidence_rows = []
    if decision is not None:
        confidence_rows = (await db.scalars(select(ConfidenceComponent).where(ConfidenceComponent.ticket_decision_id == decision.id))).all()

    previous = await db.scalar(
        select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id, ResolutionPassport.is_current.is_(True))
    )
    if previous is not None:
        await db.execute(
            update(ResolutionPassport).where(ResolutionPassport.id == previous.id).values(is_current=False)
        )

    passport = ResolutionPassport(
        schema_version=SCHEMA_VERSION, tenant_id=ticket.tenant_id, department_id=ticket.department_id,
        ticket_id=ticket.id, resolution_type=resolution_type, is_current=True, is_backfilled=is_backfilled,
        supersedes_passport_id=previous.id if previous else None,
        previous_passport_hash=previous.integrity_hash if previous else None,
        input_content_hash=content_hash(f"{ticket.subject}\n{ticket.description}"),
        classification_snapshot={"category": ticket.category, "priority": ticket.priority, "sentiment": ticket.sentiment},
        pipeline_execution_id=decision.pipeline_execution_id if decision else None,
        ticket_decision_id=decision.id if decision else None,
        response_draft_id=response_draft.id, response_version_number=response_draft.version_number,
        response_content_hash=content_hash(response_draft.content),
        citations=response_draft.citations or [],
        claim_validations=[{
            "claim_text": row.claim_text, "citation_id": row.citation_id, "validation_status": row.validation_status,
            "risk_level": row.risk_level, "reason": row.reason, "validator_version": row.validator_version,
        } for row in claim_rows],
        confidence_components=[{
            "component": row.component, "score": row.score, "passed": row.passed, "threshold": row.threshold,
        } for row in confidence_rows],
        overall_confidence=decision.overall_confidence if decision else response_draft.confidence_score,
        applicable_threshold=decision.applicable_threshold if decision else None,
        passed_gates=decision.passed_gates if decision else [],
        failed_gates=decision.failed_gates if decision else [],
        policy_id=decision.policy_id if decision else None,
        engineer_edit_ratio=engineer_edit_ratio, feedback_id=feedback_id, reviewer_id=reviewer_id,
        author_user_id=author_user_id, integrity_hash="", created_by=created_by,
    )
    passport.integrity_hash = recompute_integrity_hash(passport)
    db.add(passport)
    await db.flush()
    return passport


def internal_json(passport: ResolutionPassport, integrity_valid: bool) -> dict:
    return {
        "id": passport.id, "schema_version": passport.schema_version, "ticket_id": passport.ticket_id,
        "department_id": passport.department_id, "resolution_type": passport.resolution_type,
        "is_current": passport.is_current, "is_backfilled": passport.is_backfilled,
        "supersedes_passport_id": passport.supersedes_passport_id,
        "classification_snapshot": passport.classification_snapshot,
        "pipeline_execution_id": passport.pipeline_execution_id, "ticket_decision_id": passport.ticket_decision_id,
        "response_draft_id": passport.response_draft_id, "response_version_number": passport.response_version_number,
        "response_content_hash": passport.response_content_hash,
        "citations": passport.citations, "claim_validations": passport.claim_validations,
        "confidence_components": passport.confidence_components,
        "overall_confidence": float(passport.overall_confidence) if passport.overall_confidence is not None else None,
        "applicable_threshold": float(passport.applicable_threshold) if passport.applicable_threshold is not None else None,
        "passed_gates": passport.passed_gates, "failed_gates": passport.failed_gates,
        "policy_id": passport.policy_id, "policy_version": passport.policy_version,
        "engineer_edit_ratio": float(passport.engineer_edit_ratio) if passport.engineer_edit_ratio is not None else None,
        "feedback_id": passport.feedback_id, "reviewer_id": passport.reviewer_id, "author_user_id": passport.author_user_id,
        "integrity_hash": passport.integrity_hash, "integrity_valid": integrity_valid,
        "created_by": passport.created_by, "created_at": passport.created_at,
    }


async def customer_json(db: AsyncSession, passport: ResolutionPassport, integrity_valid: bool) -> dict:
    confirmation = await db.scalar(
        select(ResolutionConfirmation)
        .where(ResolutionConfirmation.ticket_id == passport.ticket_id)
        .order_by(ResolutionConfirmation.created_at.desc())
    )
    public_citations = [
        {"citation_id": item.get("citation_id"), "article_version": item.get("article_version")}
        for item in (passport.citations or []) if isinstance(item, dict)
    ]
    return {
        "ticket_id": passport.ticket_id, "resolution_type": passport.resolution_type,
        "public_citations": public_citations,
        "confirmation_state": confirmation.outcome if confirmation else "pending",
        "integrity_verified": integrity_valid,
        "created_at": passport.created_at,
    }
