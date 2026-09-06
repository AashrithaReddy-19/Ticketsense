"""TicketSense V2 counterfactual decision explanations.

Explanations are generated once per (ticket_decision, explanation_version)
and cached — see app.services.counterfactual.build_explanation for the pure,
deterministic generation logic. This router only fetches the latest
TicketDecision for a ticket, gets-or-creates the cached explanation, and
returns a role-appropriate view of it. It never generates an explanation
from anything other than that decision's own already-stored gates/factors.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import has_permission, is_customer
from app.database import get_db
from app.dependencies import get_current_user
from app.models.counterfactual import CounterfactualExplanation
from app.models.enterprise import TicketDecision
from app.models.user import User
from app.services.counterfactual import EXPLANATION_VERSION, build_explanation
from app.services.feature_flags import require_feature
from app.services.ticket_visibility import get_visible_ticket

router = APIRouter(prefix="/api/v2/tickets", tags=["v2-counterfactual"])


async def require_flag_enabled(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "counterfactual_explanations", user, permissions)


async def _get_or_create(db: AsyncSession, decision: TicketDecision) -> CounterfactualExplanation:
    existing = await db.scalar(
        select(CounterfactualExplanation).where(
            CounterfactualExplanation.ticket_decision_id == decision.id,
            CounterfactualExplanation.explanation_version == EXPLANATION_VERSION,
        )
    )
    if existing:
        return existing
    result = build_explanation(decision.passed_gates, decision.failed_gates, decision.factors)
    explanation = CounterfactualExplanation(
        tenant_id=decision.tenant_id, ticket_id=decision.ticket_id, ticket_decision_id=decision.id,
        explanation_version=result["explanation_version"], decision_outcome=decision.decision,
        input_passed_gates=decision.passed_gates, input_failed_gates=decision.failed_gates, input_factors=decision.factors,
        blocking_gates=result["blocking_gates"], immutable_reasons=result["immutable_reasons"],
        evidence_gaps=result["evidence_gaps"], narrative_internal=result["narrative_internal"],
        narrative_customer=result["narrative_customer"],
    )
    db.add(explanation)
    await db.flush()
    return explanation


def internal_json(explanation: CounterfactualExplanation) -> dict:
    return {
        "id": explanation.id, "ticket_id": explanation.ticket_id, "ticket_decision_id": explanation.ticket_decision_id,
        "explanation_version": explanation.explanation_version, "decision_outcome": explanation.decision_outcome,
        "blocking_gates": explanation.blocking_gates, "immutable_reasons": explanation.immutable_reasons,
        "evidence_gaps": explanation.evidence_gaps, "narrative": explanation.narrative_internal,
        "created_at": explanation.created_at,
    }


def customer_json(explanation: CounterfactualExplanation) -> dict:
    return {
        "ticket_id": explanation.ticket_id, "decision_outcome": explanation.decision_outcome,
        "requires_human_review": explanation.decision_outcome != "auto_resolve",
        "narrative": explanation.narrative_customer, "created_at": explanation.created_at,
    }


@router.get("/{ticket_id}/counterfactual")
async def get_counterfactual(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    ticket = await get_visible_ticket(db, user, ticket_id)
    decision = await db.scalar(
        select(TicketDecision).where(TicketDecision.ticket_id == ticket.id, TicketDecision.tenant_id == user.tenant_id)
        .order_by(TicketDecision.created_at.desc())
    )
    if not decision:
        raise HTTPException(404, "No automated resolution decision exists yet for this ticket")

    explanation = await _get_or_create(db, decision)
    await db.commit()
    await db.refresh(explanation)

    if is_customer(user.role):
        return customer_json(explanation)
    if not has_permission(user.role, "ticket:internal_ai"):
        raise HTTPException(403, "Permission required: ticket:internal_ai")
    return internal_json(explanation)
