"""Section 14: duplicate-ticket clustering into Admin-confirmable incidents.

Detection is a best-effort, additive side-effect of ticket creation/processing
— it never blocks or fails the request that triggered it. It only ever
creates a 'candidate' incident; an authorized Admin must explicitly confirm
one before it is treated as a declared incident (see routers/platform.py).
Every relationship this module infers is a hypothesis, not a proven cause —
callers must keep presenting it that way (see root_cause_hypothesis).
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.platform import Incident
from app.models.ticket import Ticket
from app.services.playbooks import normalize_category

logger = logging.getLogger(__name__)

MIN_CLUSTER_SIZE = 3
WINDOW_HOURS = 72
OPEN_STATUSES = ("candidate", "investigating", "confirmed")


async def detect_incident_candidate(db: AsyncSession, ticket: Ticket) -> Incident | None:
    """Best-effort: never raises, never fails the caller's transaction."""
    try:
        if not ticket.tenant_id or not ticket.department_id:
            return None
        category = normalize_category(ticket)
        since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        cluster = list((await db.scalars(
            select(Ticket).where(Ticket.tenant_id == ticket.tenant_id, Ticket.department_id == ticket.department_id,
                                  Ticket.created_at >= since, Ticket.deleted_at.is_(None))
        )).all())
        # normalize_category re-derives from free text, so filter in Python rather
        # than trusting the stored (possibly legacy-taxonomy) tickets.category column.
        cluster = [t for t in cluster if normalize_category(t) == category]
        if len(cluster) < MIN_CLUSTER_SIZE:
            return None

        existing = await db.scalar(
            select(Incident).where(Incident.tenant_id == ticket.tenant_id, Incident.department_id == ticket.department_id,
                                    Incident.category == category, Incident.status.in_(OPEN_STATUSES))
            .order_by(Incident.created_at.desc()).limit(1)
        )
        department = await db.get(Department, ticket.department_id)
        subjects = Counter(t.subject.strip().lower() for t in cluster)
        common_symptom = subjects.most_common(1)[0][0] if subjects else None
        growth_rate = round((len(cluster) / max(1, MIN_CLUSTER_SIZE) - 1) * 100, 1)
        reason = (f"{len(cluster)} tickets in the '{category}' category for {department.name if department else 'this department'} "
                  f"within the last {WINDOW_HOURS} hours (threshold: {MIN_CLUSTER_SIZE}).")

        if existing:
            existing.ticket_count = len(cluster)
            existing.growth_rate = growth_rate
            existing.common_symptom = common_symptom
            existing.detection_reason = reason
            incident = existing
        else:
            incident = Incident(tenant_id=ticket.tenant_id, department_id=ticket.department_id, category=category,
                                 title=f"Possible {category} incident — {department.name if department else 'unassigned department'}",
                                 service=department.name if department else category, status="candidate",
                                 severity="critical" if len(cluster) >= MIN_CLUSTER_SIZE * 3 else "high" if len(cluster) >= MIN_CLUSTER_SIZE * 2 else "medium",
                                 ticket_count=len(cluster), growth_rate=growth_rate, common_symptom=common_symptom, detection_reason=reason)
            db.add(incident)
            await db.flush()

        for member in cluster:
            if member.parent_incident_id is None:
                member.parent_incident_id = incident.id
        return incident
    except Exception:
        logger.info("Incident-candidate detection failed for ticket %s; continuing without it", ticket.id, exc_info=True)
        return None


async def root_cause_hypothesis(db: AsyncSession, incident: Incident) -> dict:
    """A labelled hypothesis, never presented as a confirmed cause — built only
    from real, persisted signals (recurring subjects/error codes across the
    linked tickets), with the supporting ticket ids as evidence."""
    from app.models.ai_pipeline import TechnicalEntity

    tickets = list((await db.scalars(select(Ticket).where(Ticket.parent_incident_id == incident.id))).all())
    ticket_ids = [t.id for t in tickets]
    error_codes: Counter = Counter()
    if ticket_ids:
        rows = list((await db.scalars(
            select(TechnicalEntity.raw_value).where(TechnicalEntity.ticket_id.in_(ticket_ids), TechnicalEntity.entity_type == "error_code")
        )).all())
        error_codes = Counter(rows)
    subjects = Counter(t.subject.strip().lower() for t in tickets)
    return {
        "incident_id": incident.id,
        "status": "hypothesis",
        "disclaimer": "This is an inferred hypothesis based on recurring symptoms across linked tickets — not a confirmed root cause. An authorized Admin must investigate and confirm before treating it as fact.",
        "likely_symptom": subjects.most_common(1)[0][0] if subjects else None,
        "recurring_error_codes": [{"code": code, "occurrences": count} for code, count in error_codes.most_common(5)],
        "supporting_ticket_ids": [str(t) for t in ticket_ids],
        "ticket_count": len(tickets),
    }
