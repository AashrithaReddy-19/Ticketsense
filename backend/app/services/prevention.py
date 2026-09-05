"""Section 20: evidence-backed predictive-prevention recommendations.

Every detector here reads only real, already-persisted, tenant-scoped
aggregates — ticket counts, technical-entity extractions, feedback edit
ratios, resolution-policy gate failures, article age. Nothing is estimated,
guessed, or randomly generated. Thresholds below are a documented policy
choice (not derived from any external benchmark) and exist so a detector
never fires from a handful of coincidental tickets; each is named so the
"why" is visible in code review, not just a bare number.

A recommendation is never re-created while an existing one for the same
(tenant, department, category, recommendation_type) is still open (not in a
terminal status) — re-running detection is idempotent, not a duplicate-spam
generator.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_pipeline import TechnicalEntity
from app.models.department import Department
from app.models.enterprise import TicketDecision
from app.models.feedback import Feedback
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import Incident
from app.models.prevention import PreventionRecommendation, RecommendationEvidence
from app.models.ticket import Ticket
from app.services.playbooks import normalize_category
from app.services.sla import breach_risk

WINDOW_DAYS = 30
MIN_REPEATED_CATEGORY_TICKETS = 5
MIN_ERROR_CODE_OCCURRENCES = 3
MIN_VERSION_OCCURRENCES = 3
SPIKE_RATIO_THRESHOLD = 2.0
MIN_SPIKE_BASELINE = 2
MIN_REOPEN_SAMPLE = 5
REOPEN_RATE_THRESHOLD = 0.2
MIN_EDIT_SAMPLE = 5
EDIT_RATIO_THRESHOLD = 0.5
MIN_SLA_RISK_TICKETS = 3
MIN_KNOWLEDGE_GAP_TICKETS = 3
STALE_ARTICLE_DAYS = 180

OPEN_STATUSES = ("new", "under_investigation")


def _evidence_strength(count: int, high: int, medium: int) -> str:
    return "high" if count >= high else "medium" if count >= medium else "low"


async def _existing_open(db: AsyncSession, tenant_id: UUID, department_id, category, recommendation_type: str) -> PreventionRecommendation | None:
    return await db.scalar(select(PreventionRecommendation).where(
        PreventionRecommendation.tenant_id == tenant_id, PreventionRecommendation.department_id == department_id,
        PreventionRecommendation.category == category, PreventionRecommendation.recommendation_type == recommendation_type,
        PreventionRecommendation.status.in_(OPEN_STATUSES),
    ))


async def _create(db: AsyncSession, tenant_id, department_id, category, recommendation_type: str, title: str,
                   description: str, supporting_count: int, expected_benefit: str, evidence: list[dict]) -> PreventionRecommendation | None:
    if await _existing_open(db, tenant_id, department_id, category, recommendation_type):
        return None
    strength = _evidence_strength(supporting_count, high=10, medium=5)
    rec = PreventionRecommendation(tenant_id=tenant_id, department_id=department_id, category=category,
                                    recommendation_type=recommendation_type, title=title, description=description,
                                    window_days=WINDOW_DAYS, supporting_ticket_count=supporting_count,
                                    evidence_strength=strength, expected_benefit=expected_benefit,
                                    generated_at=datetime.now(timezone.utc))
    db.add(rec)
    await db.flush()
    for item in evidence:
        db.add(RecommendationEvidence(recommendation_id=rec.id, evidence_type=item["evidence_type"],
                                       reference_id=item.get("reference_id"), detail=item.get("detail", {})))
    return rec


async def generate_recommendations(db: AsyncSession, tenant_id: UUID) -> list[PreventionRecommendation]:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    tickets = list((await db.scalars(select(Ticket).where(
        Ticket.tenant_id == tenant_id, Ticket.created_at >= since, Ticket.deleted_at.is_(None)
    ))).all())
    created: list[PreventionRecommendation] = []
    by_scope: dict[tuple, list[Ticket]] = {}
    for t in tickets:
        by_scope.setdefault((t.department_id, normalize_category(t)), []).append(t)

    for (department_id, category), scoped in by_scope.items():
        department = await db.get(Department, department_id) if department_id else None
        dept_name = department.name if department else "unassigned department"

        # 1. Repeated category — a recurring issue type with no dedicated coverage yet.
        if len(scoped) >= MIN_REPEATED_CATEGORY_TICKETS:
            rec = await _create(db, tenant_id, department_id, category, "create_knowledge_article",
                title=f"Create a knowledge article for recurring '{category}' issues in {dept_name}",
                description=f"{len(scoped)} tickets in the last {WINDOW_DAYS} days fall into the '{category}' category for {dept_name}.",
                supporting_count=len(scoped),
                expected_benefit="A documented, approved article for this recurring category could let future similar tickets cite real evidence and qualify for faster resolution.",
                evidence=[{"evidence_type": "ticket", "reference_id": t.id, "detail": {"priority": t.priority, "status": t.status}} for t in scoped[:10]])
            if rec: created.append(rec)

        # 2. High reopen rate.
        if len(scoped) >= MIN_REOPEN_SAMPLE:
            reopen_rate = sum(t.reopened_count for t in scoped) / len(scoped)
            if reopen_rate >= REOPEN_RATE_THRESHOLD:
                rec = await _create(db, tenant_id, department_id, category, "review_capacity_allocation",
                    title=f"Review capacity for '{category}' in {dept_name} — high reopen rate",
                    description=f"{reopen_rate:.0%} of {len(scoped)} tickets in '{category}' were reopened at least once in the last {WINDOW_DAYS} days.",
                    supporting_count=len(scoped),
                    expected_benefit="Investigating why resolutions in this category don't hold for customers may reduce repeat work.",
                    evidence=[{"evidence_type": "reopen_rate", "detail": {"reopen_rate": round(reopen_rate, 3), "sample_size": len(scoped)}}])
                if rec: created.append(rec)

        # 3. SLA-risk concentration.
        at_risk = [t for t in scoped if t.sla_due_at and breach_risk(t.sla_due_at, t.created_at)["status"] in ("at_risk", "breached")]
        if len(at_risk) >= MIN_SLA_RISK_TICKETS:
            rec = await _create(db, tenant_id, department_id, category, "add_monitoring",
                title=f"Add monitoring for SLA risk in '{category}' — {dept_name}",
                description=f"{len(at_risk)} of {len(scoped)} tickets in '{category}' are currently SLA at-risk or breached.",
                supporting_count=len(at_risk),
                expected_benefit="Proactive monitoring of this category's SLA countdown may catch at-risk tickets earlier.",
                evidence=[{"evidence_type": "sla_risk", "reference_id": t.id, "detail": {"status": breach_risk(t.sla_due_at, t.created_at)["status"]}} for t in at_risk[:10]])
            if rec: created.append(rec)

        # 4. Ticket spike vs. the prior window of equal length.
        midpoint = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS // 2)
        recent_half = [t for t in scoped if t.created_at >= midpoint]
        baseline_half = [t for t in scoped if t.created_at < midpoint]
        if len(baseline_half) >= MIN_SPIKE_BASELINE and len(recent_half) >= len(baseline_half) * SPIKE_RATIO_THRESHOLD:
            rec = await _create(db, tenant_id, department_id, category, "investigate_infrastructure",
                title=f"Investigate a ticket spike in '{category}' — {dept_name}",
                description=f"'{category}' tickets nearly doubled from {len(baseline_half)} to {len(recent_half)} within the {WINDOW_DAYS}-day window.",
                supporting_count=len(recent_half),
                expected_benefit="A sudden increase often traces back to a recent change, deployment, or outage worth investigating directly.",
                evidence=[{"evidence_type": "ticket_spike", "detail": {"baseline": len(baseline_half), "recent": len(recent_half)}}])
            if rec: created.append(rec)

    # 5. Common error codes (department-agnostic, tenant-wide).
    ticket_ids = [t.id for t in tickets]
    if ticket_ids:
        rows = (await db.execute(select(TechnicalEntity.normalized_value, TechnicalEntity.ticket_id).where(
            TechnicalEntity.tenant_id == tenant_id, TechnicalEntity.ticket_id.in_(ticket_ids), TechnicalEntity.entity_type == "error_code"
        ))).all()
        by_code: dict[str, list] = {}
        for code, ticket_id in rows:
            by_code.setdefault(code, []).append(ticket_id)
        for code, ids in by_code.items():
            if len(ids) >= MIN_ERROR_CODE_OCCURRENCES:
                rec = await _create(db, tenant_id, None, None, "create_knowledge_article",
                    title=f"Document recurring error code '{code}'",
                    description=f"Error code '{code}' appears in {len(ids)} tickets in the last {WINDOW_DAYS} days.",
                    supporting_count=len(ids),
                    expected_benefit="A dedicated article citing this exact error code could be retrieved and cited directly by future similar tickets.",
                    evidence=[{"evidence_type": "error_code", "reference_id": tid, "detail": {"code": code}} for tid in ids[:10]])
                if rec: created.append(rec)

        # 6. Repeated software versions.
        version_rows = (await db.execute(select(TechnicalEntity.normalized_value, TechnicalEntity.ticket_id).where(
            TechnicalEntity.tenant_id == tenant_id, TechnicalEntity.ticket_id.in_(ticket_ids), TechnicalEntity.entity_type == "version"
        ))).all()
        by_version: dict[str, list] = {}
        for version, ticket_id in version_rows:
            by_version.setdefault(version, []).append(ticket_id)
        for version, ids in by_version.items():
            if len(ids) >= MIN_VERSION_OCCURRENCES:
                rec = await _create(db, tenant_id, None, None, "investigate_version",
                    title=f"Investigate software version '{version}'",
                    description=f"Version '{version}' is mentioned in {len(ids)} tickets in the last {WINDOW_DAYS} days.",
                    supporting_count=len(ids),
                    expected_benefit="If this version has a known defect, identifying it once could prevent many individual investigations.",
                    evidence=[{"evidence_type": "version", "reference_id": tid, "detail": {"version": version}} for tid in ids[:10]])
                if rec: created.append(rec)

    # 7. High reviewer/engineer edit percentage (reuses the same signal knowledge-gaps uses).
    edit_rows = (await db.execute(
        select(Ticket.department_id, Ticket.category, func.count(), func.avg(Feedback.text_change_ratio))
        .select_from(Feedback).join(Ticket, Ticket.id == Feedback.ticket_id)
        .where(Ticket.tenant_id == tenant_id, Feedback.text_change_ratio.is_not(None), Ticket.created_at >= since)
        .group_by(Ticket.department_id, Ticket.category)
    )).all()
    for department_id, category, count, avg_ratio in edit_rows:
        if count >= MIN_EDIT_SAMPLE and float(avg_ratio or 0) >= EDIT_RATIO_THRESHOLD:
            department = await db.get(Department, department_id) if department_id else None
            rec = await _create(db, tenant_id, department_id, category, "update_knowledge_article",
                title=f"Update knowledge for '{category or 'uncategorized'}' — heavy reviewer edits",
                description=f"Reviewers changed an average of {float(avg_ratio):.0%} of the AI draft across {count} tickets in '{category or 'uncategorized'}'.",
                supporting_count=int(count),
                expected_benefit="Heavy, consistent edits suggest the cited evidence doesn't actually match what reviewers end up writing — updating it may close that gap.",
                evidence=[{"evidence_type": "edit_ratio", "detail": {"average_edit_ratio": round(float(avg_ratio), 3), "sample_size": int(count)}}])
            if rec: created.append(rec)

    # 8. Knowledge gaps (reuses the same resolution-policy-gate-failure signal as /knowledge/gaps).
    decisions = (await db.scalars(select(TicketDecision).where(
        TicketDecision.tenant_id == tenant_id, TicketDecision.created_at >= since
    ))).all()
    gap_by_category: dict[str, list] = {}
    for decision in decisions:
        if not any(gate in (decision.failed_gates or []) for gate in ("approved_current_evidence", "retrieval_relevance")):
            continue
        ticket = await db.get(Ticket, decision.ticket_id)
        if ticket:
            gap_by_category.setdefault(ticket.category or "uncategorized", []).append(ticket)
    for category, gap_tickets in gap_by_category.items():
        if len(gap_tickets) >= MIN_KNOWLEDGE_GAP_TICKETS:
            rec = await _create(db, tenant_id, None, category, "create_knowledge_article",
                title=f"Close a knowledge gap in '{category}'",
                description=f"{len(gap_tickets)} tickets in '{category}' failed the auto-resolution gate specifically for lack of approved evidence.",
                supporting_count=len(gap_tickets),
                expected_benefit="Adding approved evidence for this category directly addresses a gate that is currently blocking auto-resolution.",
                evidence=[{"evidence_type": "knowledge_gap", "reference_id": t.id, "detail": {}} for t in gap_tickets[:10]])
            if rec: created.append(rec)

    # 9. Low-performing (stale) knowledge articles.
    docs = (await db.scalars(select(KnowledgeBaseDocument).where(
        KnowledgeBaseDocument.tenant_id == tenant_id, KnowledgeBaseDocument.status == "approved"
    ))).all()
    now = datetime.now(timezone.utc)
    for doc in docs:
        age_days = (now - doc.updated_at).days if doc.updated_at else 0
        if age_days > STALE_ARTICLE_DAYS:
            rec = await _create(db, tenant_id, doc.department_id, None, "update_knowledge_article",
                title=f"Review stale article: {doc.title}",
                description=f"'{doc.title}' has not been updated in {age_days} days.",
                supporting_count=1,
                expected_benefit="Reviewing an old article for continued accuracy reduces the risk of citing outdated guidance.",
                evidence=[{"evidence_type": "stale_article", "reference_id": doc.id, "detail": {"age_days": age_days}}])
            if rec: created.append(rec)

    # 10. Confirmed/investigating incidents worth a customer-facing announcement.
    incidents = (await db.scalars(select(Incident).where(
        Incident.tenant_id == tenant_id, Incident.status.in_(("investigating", "confirmed"))
    ))).all()
    for incident in incidents:
        rec = await _create(db, tenant_id, incident.department_id, incident.category, "publish_customer_announcement",
            title=f"Consider a customer announcement for '{incident.title}'",
            description=f"An incident affecting {incident.ticket_count} tickets is currently {incident.status}.",
            supporting_count=incident.ticket_count,
            expected_benefit="A proactive announcement may reduce duplicate tickets from customers experiencing the same issue.",
            evidence=[{"evidence_type": "incident", "reference_id": incident.id, "detail": {"status": incident.status}}])
        if rec:
            rec.linked_incident_id = incident.id
            created.append(rec)

    return created
