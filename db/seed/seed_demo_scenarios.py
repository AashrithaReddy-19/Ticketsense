"""Seeds a small, deterministic set of curated demonstration tickets covering
the eight scenarios a live walkthrough of TicketSense needs to show:

  1. A safe, high-confidence ticket that genuinely auto-resolves.
  2. A low-confidence VPN ticket that gets routed to the specialized VPN
     Engineer.
  3. A sensitive payment ticket that is fail-closed blocked from auto-resolution.
  4. Three similar SAP tickets that produce a real incident candidate.
  5. A ticket resolved by a human with no cited evidence, producing a real
     knowledge-gap draft article.
  6. One ticket that is genuinely SLA at-risk.
  7. One ticket used to demonstrate a real, sandboxed safe action.
  8. A predictive-prevention recommendation, generated from the same SAP
     cluster as scenario 4 (five tickets clears both the incident-candidate
     threshold of 3 and the repeated-category prevention threshold of 5).

This script deliberately does NOT special-case any of these scenarios inside
application code -- every outcome (auto-resolve vs. blocked vs. assigned,
which incident/recommendation gets created) is produced by calling the real,
unmodified production service functions (``resolution_policy.process_resolution_decision``,
``workflow.auto_assign_ticket``, ``incidents.detect_incident_candidate``,
``prevention.generate_recommendations``) or the real HTTP API, exactly as a
live ticket would be. The only "demo-specific" thing here is the *input data*
(realistic ticket text and, for scenarios 1-3, a directly-constructed AIDraft
so the outcome is deterministic rather than depending on the live embedding/
classifier models) -- never a shortcut inside the services themselves.

Idempotent: every seeded ticket's subject starts with "[Demo] " and is looked
up by exact subject before creating anything, so re-running this script is
safe and never creates duplicates. None of these subjects match any pattern
in db/maintenance/cleanup_test_pollution.py, so this curated data is never at
risk of being swept up by that script.

Usage (from backend/, so the uv-managed venv/container has every app dependency):
    uv run python ../db/seed/seed_demo_scenarios.py
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import async_session_maker
from app.main import app
from app.models.ai_draft import AIDraft
from app.models.ai_pipeline import PipelineExecution
from app.models.department import Department
from app.models.platform import Organization
from app.models.ticket import Ticket
from app.models.user import User
from app.services.incidents import detect_incident_candidate
from app.services.prevention import generate_recommendations
from app.services.resolution_policy import process_resolution_decision
from app.services.sla import compute_sla_due_at

DEMO_TENANT_SLUG = "ticketsense-demo"


def grounded_validation(confidence: float, margin: float, coverage: float, valid: bool = True) -> dict:
    return {
        "confidence_score": confidence,
        "confidence_features": {"classification_probability": confidence, "classification_margin": margin},
        "citation_coverage": coverage, "valid": valid,
        "grounding": {"blocked": not valid, "overall_status": "Grounded" if valid else "Ungrounded"},
    }


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


async def existing_ticket_id(db, tenant_id, subject: str):
    return await db.scalar(select(Ticket.id).where(Ticket.tenant_id == tenant_id, Ticket.subject == subject))


async def seed_ai_resolved_ticket(db, tenant_id, department_id, customer_id) -> None:
    subject = "[Demo] VPN client fails to connect after the Windows update"
    if await existing_ticket_id(db, tenant_id, subject):
        print(f"  skip (exists): {subject}")
        return
    ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id, subject=subject,
                     description="After installing the latest Windows update, the corporate VPN client fails to establish a connection.",
                     status="ai_processing", priority="medium", sentiment="neutral", confidence_score=0.95)
    db.add(ticket)
    await db.flush()
    evidence = [{"citation_id": "KB-VPN-CLIENT", "chunk_text": "Clear the VPN client's cached session credentials and reconnect using the current client version.",
                 "status": "approved", "is_publishable": True, "article_version": "1.0", "similarity": 0.93,
                 "tenant_id": str(tenant_id), "department_id": str(department_id)}]
    draft = AIDraft(tenant_id=tenant_id, ticket_id=ticket.id, department_id=department_id, article_version="1.0",
                     draft_text="Clear the VPN client's cached session credentials and reconnect using the current client version. [KB-VPN-CLIENT]",
                     citations=[{"citation_id": "KB-VPN-CLIENT"}], evidence=evidence, generation_status="ready",
                     citation_validation_status="valid", validation_details=grounded_validation(0.95, 0.5, 1.0))
    db.add(draft)
    execution = PipelineExecution(tenant_id=tenant_id, ticket_id=ticket.id, pipeline_version="demo-seed-1.0", trigger_type="seed",
                                   status="completed", started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
                                   fallback_used=False, correlation_id=uuid4())
    db.add(execution)
    await db.flush()
    draft.validation_details = {**draft.validation_details, "execution_id": str(execution.id)}
    await db.commit()
    decision = await process_resolution_decision(db, ticket)
    await db.commit()
    print(f"  created: {subject} -> decision={decision.decision}")


async def seed_low_confidence_vpn_ticket(db, tenant_id, department_id, customer_id) -> None:
    subject = "[Demo] Intermittent VPN disconnects on a newly issued laptop"
    if await existing_ticket_id(db, tenant_id, subject):
        print(f"  skip (exists): {subject}")
        return
    ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id, subject=subject,
                     description="A newly issued laptop keeps dropping the VPN connection every few minutes; the cause is not yet clear.",
                     status="ai_processing", priority="medium", sentiment="neutral", confidence_score=0.5)
    db.add(ticket)
    await db.flush()
    draft = AIDraft(tenant_id=tenant_id, ticket_id=ticket.id, department_id=department_id, article_version="1.0",
                     draft_text="Unclear; no strongly matching evidence was found.", citations=[], evidence=[],
                     generation_status="ready", citation_validation_status="unverified",
                     validation_details=grounded_validation(0.5, 0.05, 0.0, valid=False))
    db.add(draft)
    execution = PipelineExecution(tenant_id=tenant_id, ticket_id=ticket.id, pipeline_version="demo-seed-1.0", trigger_type="seed",
                                   status="completed", started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
                                   fallback_used=False, correlation_id=uuid4())
    db.add(execution)
    await db.flush()
    draft.validation_details = {**draft.validation_details, "execution_id": str(execution.id)}
    await db.commit()
    decision = await process_resolution_decision(db, ticket)
    await db.commit()
    await db.refresh(ticket)
    print(f"  created: {subject} -> decision={decision.decision}, assignee={ticket.assignee_id}")


async def seed_sensitive_payment_ticket(db, tenant_id, department_id, customer_id) -> None:
    subject = "[Demo] Customer disputes a duplicate credit card charge"
    if await existing_ticket_id(db, tenant_id, subject):
        print(f"  skip (exists): {subject}")
        return
    ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id, subject=subject,
                     description="The customer was charged twice for the same order and is requesting the duplicate payment be reversed.",
                     status="ai_processing", priority="high", sentiment="negative", confidence_score=0.9)
    db.add(ticket)
    await db.flush()
    evidence = [{"citation_id": "KB-PAY-001", "chunk_text": "Look up the transaction ID in the payment processor's dashboard before taking any action.",
                 "status": "approved", "is_publishable": True, "article_version": "1.0", "similarity": 0.9,
                 "tenant_id": str(tenant_id), "department_id": str(department_id)}]
    draft = AIDraft(tenant_id=tenant_id, ticket_id=ticket.id, department_id=department_id, article_version="1.0",
                     draft_text="Look up the transaction ID in the payment processor's dashboard before taking any action. [KB-PAY-001]",
                     citations=[{"citation_id": "KB-PAY-001"}], evidence=evidence, generation_status="ready",
                     citation_validation_status="valid", validation_details=grounded_validation(0.9, 0.4, 1.0))
    db.add(draft)
    execution = PipelineExecution(tenant_id=tenant_id, ticket_id=ticket.id, pipeline_version="demo-seed-1.0", trigger_type="seed",
                                   status="completed", started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
                                   fallback_used=False, correlation_id=uuid4())
    db.add(execution)
    await db.flush()
    draft.validation_details = {**draft.validation_details, "execution_id": str(execution.id)}
    await db.commit()
    decision = await process_resolution_decision(db, ticket)
    await db.commit()
    await db.refresh(ticket)
    assert decision.decision != "auto_resolve", "a sensitive payment ticket must never auto-resolve, even with strong synthetic evidence"
    print(f"  created: {subject} -> decision={decision.decision} (correctly blocked), assignee={ticket.assignee_id}")


async def seed_sap_cluster(db, tenant_id, department_id, customer_id) -> list[Ticket]:
    """Five near-duplicate SAP tickets: satisfies both the incident-candidate
    cluster threshold (>=3) and the prevention repeated-category threshold (>=5)
    from a single, understandable scenario."""
    base_subject = "[Demo] SAP IDoc stuck in status 51 after the nightly batch job"
    tickets = []
    for i in range(1, 6):
        subject = base_subject if i == 1 else f"{base_subject} ({i})"
        existing = await existing_ticket_id(db, tenant_id, subject)
        if existing:
            tickets.append(await db.get(Ticket, existing))
            continue
        ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id, subject=subject,
                         description="An outbound IDoc is stuck in status 51 (application document not posted) after last night's batch run; T-code WE02 shows the error.",
                         status="routed", priority="medium", sentiment="neutral", category="sap")
        db.add(ticket)
        await db.flush()
        tickets.append(ticket)
    await db.commit()
    print(f"  seeded {len(tickets)} SAP cluster ticket(s) (existing rows reused where already present)")
    return tickets


async def seed_incident_candidate(db, cluster: list[Ticket]) -> None:
    incident = await detect_incident_candidate(db, cluster[-1])
    await db.commit()
    if incident:
        print(f"  incident candidate: '{incident.title}' (status={incident.status}, tickets={incident.ticket_count})")
    else:
        print("  no new incident candidate created (one may already be open for this category)")


async def seed_prevention_recommendation(db, tenant_id) -> None:
    recommendations = await generate_recommendations(db, tenant_id)
    await db.commit()
    if recommendations:
        for rec in recommendations:
            print(f"  prevention recommendation: '{rec.title}' (evidence_strength={rec.evidence_strength}, supporting_count={rec.supporting_ticket_count})")
    else:
        print("  no new prevention recommendation created (one may already be open, or evidence didn't clear a threshold this run)")


async def seed_sla_at_risk_ticket(db, tenant_id, department_id, customer_id) -> None:
    subject = "[Demo] Shared drive permissions not syncing for a new hire"
    if await existing_ticket_id(db, tenant_id, subject):
        print(f"  skip (exists): {subject}")
        return
    created_at = datetime.now(timezone.utc) - timedelta(hours=7, minutes=30)
    ticket = Ticket(tenant_id=tenant_id, submitted_by=customer_id, department_id=department_id, subject=subject,
                     description="A new hire's shared drive permissions have not synced two days after their account was provisioned.",
                     status="routed", priority="high", sentiment="neutral", created_at=created_at)
    db.add(ticket)
    await db.flush()
    ticket.sla_due_at = await compute_sla_due_at(db, tenant_id, ticket.priority, created_at)
    await db.commit()
    print(f"  created: {subject} (sla_due_at={ticket.sla_due_at.isoformat()}, now genuinely SLA at-risk)")


async def seed_knowledge_gap_ticket(client: AsyncClient, tenant_engineer_department: str) -> None:
    subject = "[Demo] VPN reconnect issue resolved without a cited knowledge article"
    customer = await token(client, "customer@demo.com")
    sysadmin_token = await token(client, "sysadmin@demo.com")
    listed = await client.get("/api/tickets", headers=auth(sysadmin_token), params={"q": subject})
    if listed.status_code == 200 and any(row["subject"] == subject for row in listed.json()):
        print(f"  skip (exists): {subject}")
        return
    engineer = await token(client, "agent@demo.com")
    team_lead = await token(client, "teamlead@demo.com")
    reviewer = await token(client, "reviewer@demo.com")
    created = await client.post("/api/tickets", headers=auth(customer), json={
        "subject": subject, "description": "The VPN dropped once after a router firmware update and reconnected on its own; customer just wants it logged.",
    })
    if created.status_code != 201:
        print(f"  skip ({subject}): ticket creation returned {created.status_code}: {created.text[:200]}")
        return
    ticket_id = created.json()["id"]
    engineer_profile = await client.get("/api/auth/me", headers=auth(engineer))
    await client.post(f"/api/tickets/{ticket_id}/assign", headers=auth(team_lead), json={"engineer_id": engineer_profile.json()["id"], "comment": "Assigning for the demo knowledge-gap scenario"})
    await client.post(f"/api/tickets/{ticket_id}/start-work", headers=auth(engineer), json={"comment": "Investigating"})
    await client.post(f"/api/tickets/{ticket_id}/drafts", headers=auth(engineer), json={"content": "The router firmware update caused a brief VPN drop; it reconnected automatically once the update completed. No action needed.", "citations": []})
    await client.post(f"/api/tickets/{ticket_id}/submit-for-review", headers=auth(engineer), json={"comment": "Ready for review"})
    reviewed = await client.post(f"/api/tickets/{ticket_id}/review", headers=auth(reviewer), json={"action": "approve", "review_comment": "Confirmed with the customer"})
    print(f"  created: {subject} -> review={reviewed.status_code} (a knowledge-gap draft article should now exist, citing this ticket)")


async def seed_safe_action_ticket(client: AsyncClient) -> None:
    """Mentioning "VPN" lets the real ticket-intake pipeline auto-route this to
    Networking and auto-assign it to the VPN Engineer on its own -- exactly the
    same routing path scenario 2 exercises -- so no manual assign call, and no
    guessing at who the assignee will be, is needed here."""
    subject = "[Demo] Customer asking whether their VPN account is locked out"
    sysadmin_token = await token(client, "sysadmin@demo.com")
    listed = await client.get("/api/tickets", headers=auth(sysadmin_token), params={"q": subject})
    if listed.status_code == 200 and any(row["subject"] == subject for row in listed.json()):
        print(f"  skip (exists): {subject}")
        return
    customer = await token(client, "customer@demo.com")
    created = await client.post("/api/tickets", headers=auth(customer), json={
        "subject": subject, "description": "I tried logging into the VPN a few times and I'm not sure if my account got locked; can someone check?",
    })
    if created.status_code != 201:
        print(f"  skip ({subject}): ticket creation returned {created.status_code}: {created.text[:200]}")
        return
    ticket_id = created.json()["id"]
    detail = await client.get(f"/api/tickets/{ticket_id}", headers=auth(sysadmin_token))
    assignee_id = detail.json().get("assignee_id")
    if not assignee_id:
        print(f"  created: {subject}, but no engineer was auto-assigned -- skipping the safe-action execution")
        return
    engineer = await token(client, "agent@demo.com")
    executed = await client.post("/api/safe-actions/check_account_lock_status/execute", headers={**auth(engineer), "Idempotency-Key": uuid4().hex},
                                  json={"parameters": {"email": "customer@demo.com"}, "confirm": True, "ticket_id": ticket_id})
    print(f"  created: {subject} -> auto-assigned={assignee_id}, safe action execution={executed.status_code}")


async def main() -> None:
    async with async_session_maker() as db:
        tenant = await db.scalar(select(Organization).where(Organization.slug == DEMO_TENANT_SLUG))
        if not tenant:
            raise SystemExit(f"No tenant with slug '{DEMO_TENANT_SLUG}' -- run db/seed/run_seed.py first.")
        tenant_id = tenant.id
        departments = {d.name: d.id for d in (await db.scalars(select(Department).where(Department.tenant_id == tenant_id))).all()}
        customer_id = await db.scalar(select(User.id).where(User.tenant_id == tenant_id, User.email == "customer@demo.com"))
        if not customer_id:
            raise SystemExit("customer@demo.com not found -- run db/seed/run_seed.py first.")

        print("1. AI-resolved ticket (safe, high-confidence, cited)")
        await seed_ai_resolved_ticket(db, tenant_id, departments["Networking"], customer_id)

        print("2. Low-confidence VPN ticket routed to a VPN Engineer")
        await seed_low_confidence_vpn_ticket(db, tenant_id, departments["Networking"], customer_id)

        print("3. Sensitive payment ticket, fail-closed blocked from auto-resolution")
        await seed_sensitive_payment_ticket(db, tenant_id, departments["Payments"], customer_id)

        print("4 & 8. SAP ticket cluster -> incident candidate + prevention recommendation")
        cluster = await seed_sap_cluster(db, tenant_id, departments["SAP"], customer_id)
        await seed_incident_candidate(db, cluster)
        await seed_prevention_recommendation(db, tenant_id)

        print("6. SLA at-risk ticket")
        await seed_sla_at_risk_ticket(db, tenant_id, departments["Networking"], customer_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        print("5. Human resolution without cited evidence -> knowledge-gap draft")
        await seed_knowledge_gap_ticket(client, "Networking")

        print("7. Safe-action demonstration ticket")
        await seed_safe_action_ticket(client)

    print("\nDemo scenarios seeded.")


if __name__ == "__main__":
    asyncio.run(main())
