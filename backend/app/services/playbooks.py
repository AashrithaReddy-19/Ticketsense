"""Section 13: playbook matching, application, and lifecycle transitions.

A playbook only ever recommends and structures diagnostic work — the
resolution-policy gate (services/resolution_policy.py) remains the sole
authority on whether a ticket may auto-resolve. A matched playbook can only
ever add a restriction (force human review when it says it isn't eligible for
auto-resolution) — see ``playbook_gate`` — never bypass any existing gate.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_pipeline import TechnicalEntity
from app.models.enterprise import DiagnosticPlan, DiagnosticStep
from app.models.playbook import Playbook, PlaybookApplication
from app.models.ticket import Ticket


def normalize_category(ticket: Ticket) -> str:
    """The single, canonical category taxonomy for policy/playbook matching.

    ``tickets.category`` itself is not reliable for this: the legacy intake
    classifier (services/ticket_intelligence.py) writes capitalized department
    names like "Networking" or "SAP" at ticket-creation time, and only gets
    overwritten with this lowercase vocabulary once the resolution-policy gate
    has actually run for that ticket. Re-deriving it from the ticket's own
    text (which normalize_category already does) means playbook matching
    works consistently regardless of which stage last touched the ticket.
    """
    text = f"{ticket.category or ''} {ticket.subject} {ticket.description}".lower()
    for category, terms in (
        ("vpn", ("vpn", "virtual private network")),
        ("payment", ("payment", "billing", "transaction")),
        ("security", ("security", "breach", "credential", "malware")),
        ("sap", ("sap", "tcode", "idoc")),
        ("cloud", ("cloud", "aws", "azure", "s3", "ec2")),
        ("hr_systems", ("payroll", "leave", "hr system")),
        ("network", ("network", "dns", "wifi", "firewall")),
    ):
        if any(term in text for term in terms):
            return category
    return "general_it"


async def _error_codes(db: AsyncSession, ticket: Ticket) -> set[str]:
    """Prefers the real, already-extracted technical_entities rows for this
    ticket (from the LangGraph pipeline's entity-extraction stage); falls back
    to a crude digit-containing-word heuristic over the raw text when the
    pipeline hasn't run yet for this ticket (e.g. at intake time)."""
    entities = list((await db.scalars(
        select(TechnicalEntity.raw_value).where(TechnicalEntity.ticket_id == ticket.id, TechnicalEntity.entity_type == "error_code")
    )).all())
    if entities:
        return {str(v).lower() for v in entities}
    text = f"{ticket.subject} {ticket.description}".lower()
    return {word.strip(".,!?") for word in text.split() if any(ch.isdigit() for ch in word)}


async def match_playbook(db: AsyncSession, ticket: Ticket, category: str | None = None) -> Playbook | None:
    """Deterministic best-match: active playbooks in this ticket's category,
    ranked by applicable-error-code overlap, then by highest version.

    ``category`` lets a caller (the resolution-policy gate) pass the
    just-computed category explicitly; every other caller re-derives it via
    normalize_category() rather than trusting ticket.category, which may still
    hold the legacy intake classifier's different taxonomy (see
    normalize_category's docstring)."""
    if not ticket.tenant_id:
        return None
    category = (category or normalize_category(ticket)).lower()
    candidates = list((await db.scalars(
        select(Playbook).where(Playbook.tenant_id == ticket.tenant_id, Playbook.status == "active")
    )).all())
    in_category = [p for p in candidates if p.category.lower() == category]
    if not in_category:
        return None
    ticket_codes = await _error_codes(db, ticket)
    def score(playbook: Playbook) -> tuple[int, int]:
        codes = {str(c).lower() for c in playbook.applicable_error_codes}
        overlap = len(codes & ticket_codes)
        return (overlap, playbook.version)
    return max(in_category, key=score)


def playbook_gate(playbook: Playbook | None) -> tuple[bool, str]:
    """Returns (passed, detail) for the resolution-policy gate list. No matched
    playbook is neutral (passes) — a category without a playbook must not be
    blocked from auto-resolution by that fact alone."""
    if playbook is None:
        return True, "No matching playbook; not a blocking factor"
    if playbook.auto_resolution_eligible:
        return True, f"Playbook '{playbook.title}' v{playbook.version} allows auto-resolution"
    return False, f"Playbook '{playbook.title}' v{playbook.version} requires human review"


async def record_recommendation(db: AsyncSession, ticket: Ticket, playbook: Playbook) -> None:
    db.add(PlaybookApplication(tenant_id=ticket.tenant_id, playbook_id=playbook.id, ticket_id=ticket.id,
                               applied_by=None, application_type="recommended"))


async def apply_playbook(db: AsyncSession, ticket: Ticket, playbook: Playbook, user_id) -> DiagnosticPlan:
    """Copies the playbook's diagnostic_steps_template into a real, per-ticket
    DiagnosticPlan/DiagnosticStep pair — the same structures an Engineer's
    manually authored diagnostic plan uses (see routers/enterprise.py). This is
    an intentional copy, not a live reference: editing the playbook later must
    never retroactively change a step already shown for this ticket."""
    plan = DiagnosticPlan(tenant_id=ticket.tenant_id, ticket_id=ticket.id, created_by=user_id,
                           summary=f"From playbook: {playbook.title} (v{playbook.version})")
    db.add(plan)
    await db.flush()
    for sequence, step in enumerate(playbook.diagnostic_steps_template, 1):
        db.add(DiagnosticStep(plan_id=plan.id, sequence_number=sequence, title=str(step.get("title", ""))[:255],
                               instruction=str(step.get("instruction", "")), safety_warning=step.get("safety_warning"),
                               evidence_required=bool(step.get("evidence_required", False))))
    db.add(PlaybookApplication(tenant_id=ticket.tenant_id, playbook_id=playbook.id, ticket_id=ticket.id,
                                diagnostic_plan_id=plan.id, applied_by=user_id, application_type="applied"))
    return plan


async def next_version(db: AsyncSession, tenant_id, playbook_key: str) -> int:
    versions = await db.scalars(select(Playbook.version).where(Playbook.tenant_id == tenant_id, Playbook.playbook_key == playbook_key))
    return max(list(versions), default=0) + 1
