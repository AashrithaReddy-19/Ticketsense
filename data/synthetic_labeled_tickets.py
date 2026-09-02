"""Inserts a small hand-authored, fully-labeled ticket set into the `tickets` table —
department, priority, AND sentiment all filled in — so the classifier
(ai/models/train_classifier.py) has something to train on.

This exists because the real external dataset (data/import_helpdesk_tickets.py) predates
the SAP/Networking/Cloud/HR taxonomy and doesn't have a sentiment field at all. Each of
these ~96 tickets is grounded in one of the 48 db/seed/knowledge_base/ articles (2 tickets
per article), phrased the way an end user would actually write it, not like the KB's SOP
text — so retrieval and classification can both be sanity-checked against the same set of
real-world issues without the labels being suspiciously identical to the KB content.

Requires seed.sql to have been applied first (needs the 4 department rows).

Usage (from backend/):
    uv run python ../data/synthetic_labeled_tickets.py [--reset]
"""

import argparse
import asyncio
import os
import re
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BULK_IMPORT_EMAIL = "synthetic-tickets@ticketsense.local"

# (department, subject, description, priority, sentiment) — 2 per KB topic, ~96 total.
TICKETS = [
    # --- SAP ---
    ("SAP", "Can't post goods receipt - ME023 error",
     "Getting error ME023 'item is blocked' when I try to do a goods receipt in MIGO for "
     "PO 4500012345. This is holding up our receiving dock.", "high", "negative"),
    ("SAP", "ME023 block on PO receipt",
     "MIGO keeps throwing ME023 for a PO item, says it's blocked. Can someone check what's "
     "blocking it?", "medium", "neutral"),
    ("SAP", "Locked out of SAP",
     "I can't log into SAP GUI anymore, it says my user is locked. I have month-end close "
     "today and need access urgently.", "urgent", "negative"),
    ("SAP", "SAP account locked, need reset",
     "Think I fat-fingered my password too many times, SAP says I'm locked out. Can you "
     "unlock when you get a chance?", "medium", "neutral"),
    ("SAP", "SAP GUI won't connect",
     "SAP GUI just hangs on 'Connecting to server' and eventually times out. Been like this "
     "all morning, can't get any work done.", "high", "negative"),
    ("SAP", "Slow SAP GUI connection",
     "Noticing SAP GUI takes a long time to connect lately, sometimes times out. Not urgent "
     "but wanted to flag it.", "low", "neutral"),
    ("SAP", "No authorization for ME21N",
     "I'm trying to run ME21N to create a PO and getting 'not authorized for this "
     "transaction'. I need this for my new procurement role.", "medium", "neutral"),
    ("SAP", "Missing transaction access after role change",
     "Since my department transfer I've lost access to several transactions I used to have, "
     "including MIRO. Blocking my invoice work.", "high", "negative"),
    ("SAP", "Nightly batch job hasn't finished",
     "Our nightly MRP batch job has been showing 'Active' in SM37 for 3 hours now with no "
     "progress. This usually only takes 40 minutes.", "urgent", "negative"),
    ("SAP", "Background job stuck in Released",
     "Scheduled a background job yesterday and it's still sitting in Released status, hasn't "
     "started. Can someone take a look when free?", "medium", "neutral"),
    ("SAP", "Invoice print didn't come out",
     "Printed a customer invoice from SAP twice now and nothing's coming out of the printer "
     "or showing in the queue. Customer is waiting.", "high", "negative"),
    ("SAP", "Can't find spool request for PO printout",
     "Tried printing a PO earlier, not sure it went through. Could someone check if there's "
     "a spool request for it?", "low", "neutral"),
    ("SAP", "Wrong exchange rate on FI posting",
     "A EUR invoice posted today used an exchange rate that looks way off compared to "
     "today's rate. This is going to throw off our books.", "high", "negative"),
    ("SAP", "Exchange rate question on FI document",
     "Noticed the exchange rate on document 1900012 looks different than expected, just "
     "want to confirm it's correct before month-end.", "medium", "neutral"),
    ("SAP", "PO stuck waiting for release",
     "My purchase order has been sitting for release approval for over a week now and the "
     "vendor is asking when we'll confirm. Can someone check the release strategy?",
     "high", "negative"),
    ("SAP", "Question about PO release status",
     "Just checking - is my PO 4500098765 still waiting on approval? Wanted to confirm "
     "before following up with my manager.", "low", "neutral"),
    ("SAP", "Material master locked, can't update pricing",
     "Trying to update pricing on a material and it says it's locked by another user who I "
     "don't think is even working on it right now. Need this done today.", "high", "negative"),
    ("SAP", "Material locked error in MM02",
     "Getting a 'material locked' message when opening MM02 for one of our SKUs. Not "
     "urgent, just want it looked at.", "low", "neutral"),
    ("SAP", "Orders not coming through from EDI partner",
     "We haven't seen any new sales orders from our EDI partner since yesterday. Checked "
     "and there are several IDocs sitting in error status 51. This is affecting order "
     "fulfillment.", "urgent", "negative"),
    ("SAP", "One IDoc failed with status 51",
     "Noticed a single inbound IDoc in status 51 this morning, the rest look fine. Can "
     "someone check what's wrong with it?", "medium", "neutral"),
    ("SAP", "Report crashes with error screen",
     "Running my usual sales report and it crashes to an error screen every time now "
     "instead of showing results. Worked fine last week.", "high", "negative"),
    ("SAP", "Occasional dump when running custom report",
     "Every so often our custom Z-report throws a dump. Doesn't happen every time, just "
     "wanted to flag it in case it's a pattern.", "low", "neutral"),
    ("SAP", "Can't create new sales orders - number range error",
     "Nobody on my team can create new sales orders right now, getting an error about no "
     "more numbers available. This is blocking the whole sales floor.", "urgent", "negative"),
    ("SAP", "Number range question for new document type",
     "Setting up a new document type and want to check the number range interval has "
     "enough room before we go live next month.", "low", "positive"),
    # --- Networking ---
    ("Networking", "VPN won't connect from home",
     "Working from home today and VPN just hangs on Connecting and never gets in. Tried "
     "restarting twice already. I have a client call in an hour and need internal access.",
     "urgent", "negative"),
    ("Networking", "VPN connection issue",
     "My VPN client isn't connecting this morning, just wanted to flag it in case others "
     "are seeing the same thing.", "medium", "neutral"),
    ("Networking", "Wifi keeps dropping at my desk",
     "My laptop keeps disconnecting from the office wifi every 10-15 minutes, it's really "
     "disrupting my video calls today.", "high", "negative"),
    ("Networking", "Occasional wifi drop near the kitchen area",
     "Noticed my connection drops occasionally when I'm near the kitchen. Minor annoyance, "
     "not blocking anything.", "low", "neutral"),
    ("Networking", "Can't reach internal wiki by name",
     "intranet.company.local won't load for me, just times out, but it works fine by IP. "
     "Need the wiki for a deadline today.", "high", "negative"),
    ("Networking", "Internal hostname not resolving",
     "Getting a DNS error trying to reach one of our internal tools by hostname. Works for "
     "my coworker so might just be me.", "medium", "neutral"),
    ("Networking", "Shared drive disconnected, need files now",
     "My mapped drive to the finance share shows a red X and I can't open it. I need a "
     "file off there for a meeting in 20 minutes.", "urgent", "negative"),
    ("Networking", "Mapped drive shows disconnected",
     "My H: drive mapping shows as disconnected today. Can someone help reconnect it when "
     "they have a moment?", "low", "neutral"),
    ("Networking", "Need firewall rule opened for new vendor tool",
     "We're rolling out a new SaaS integration and need outbound access to a specific port "
     "opened. Can you help scope the request? No rush this week.", "low", "positive"),
    ("Networking", "Integration failing, likely blocked port",
     "Our new integration test is failing and I suspect it's a firewall block on our end. "
     "This is holding up a deployment planned for tomorrow.", "high", "negative"),
    ("Networking", "No internet, laptop shows limited connectivity",
     "My laptop says 'limited' connectivity and I can't get online at all. Tried "
     "reconnecting to wifi already. Need this fixed, I'm losing work time.", "high", "negative"),
    ("Networking", "New laptop not getting proper IP",
     "Just got a new laptop and it's showing a weird 169 IP address instead of connecting "
     "normally. Can someone take a look?", "medium", "neutral"),
    ("Networking", "Calls keep freezing during client meetings",
     "My video calls have been freezing and dropping constantly this week, it's happening "
     "during important client meetings and looks unprofessional.", "high", "negative"),
    ("Networking", "Minor lag on video calls today",
     "Noticing a bit of lag on Teams calls today, nothing major, just wanted to mention "
     "it.", "low", "neutral"),
    ("Networking", "Need guest wifi for visitor tomorrow",
     "We have a vendor visiting tomorrow and I'd like to get them set up with guest wifi "
     "access. Whenever is convenient works.", "low", "positive"),
    ("Networking", "Guest wifi code not working for our visitor",
     "The guest access I set up earlier isn't working for our visitor who's here right now "
     "waiting to present.", "high", "negative"),
    ("Networking", "No network at my new desk",
     "I moved to a new desk this week and the ethernet port shows no connection at all. "
     "Been running off wifi as a workaround but it's not ideal.", "medium", "neutral"),
    ("Networking", "Ethernet port dead at new desk, need it today",
     "My network port isn't working and I really need a wired connection today for a large "
     "file transfer. Can this be prioritized?", "high", "negative"),
    ("Networking", "Proxy blocking a site I need for work",
     "A vendor documentation site I need is getting blocked by the proxy. Would like it "
     "allowlisted when possible, not blocking me today.", "low", "neutral"),
    ("Networking", "Can't access required tool, proxy block",
     "The proxy is blocking a tool our team relies on daily and it just started today. "
     "This is stopping several people from working.", "urgent", "negative"),
    ("Networking", "Can't reach HQ systems from branch office",
     "Nobody at our branch can reach the systems at HQ this morning, internet itself seems "
     "fine. Whole office is affected.", "urgent", "negative"),
    ("Networking", "Intermittent connection to HQ",
     "Seeing occasional connectivity drops to HQ systems throughout the day, not constant "
     "but happening a few times an hour.", "high", "neutral"),
    ("Networking", "Desk network port suddenly stopped working",
     "My network port worked fine yesterday and now shows no link at all today, nothing "
     "changed on my end.", "medium", "neutral"),
    ("Networking", "Whole row of desks lost network",
     "Several of us in the same row just lost our wired network connection at the same "
     "time. Seems bigger than just one desk.", "urgent", "negative"),
    # --- Cloud ---
    ("Cloud", "App getting Access Denied from S3",
     "Our production service just started throwing Access Denied errors reading from the "
     "reports bucket. This is affecting live customer reports.", "urgent", "negative"),
    ("Cloud", "S3 access denied in dev environment",
     "Getting an access denied error trying to read from an S3 bucket in our dev "
     "environment, not blocking prod, just want it sorted before I continue testing.",
     "medium", "neutral"),
    ("Cloud", "Need IAM access to new project's resources",
     "Starting on the new analytics project and need read access to its S3 bucket and "
     "Redshift cluster. No immediate rush.", "low", "positive"),
    ("Cloud", "Missing permissions blocking deployment",
     "Our deploy pipeline needs IAM permissions it doesn't currently have, and this is "
     "blocking today's release.", "high", "negative"),
    ("Cloud", "Can't SSH into new EC2 instance",
     "Just launched a new EC2 instance and can't SSH in at all, connection just times out. "
     "Would like this working today if possible.", "medium", "neutral"),
    ("Cloud", "Production instance unreachable",
     "One of our production instances suddenly became unreachable via SSH, we can't get in "
     "to investigate why the service is down.", "urgent", "negative"),
    ("Cloud", "Backup job failing, storage quota hit",
     "Our nightly backup job failed last night with a quota exceeded error. This has been "
     "building up for a while, would like it addressed soon.", "high", "negative"),
    ("Cloud", "Approaching storage quota",
     "Noticed we're getting close to our storage quota on one of our buckets, wanted to "
     "raise it before it becomes a problem.", "low", "neutral"),
    ("Cloud", "Need urgent restore, accidentally deleted volume",
     "I accidentally deleted a volume that had important data on it. Need this restored "
     "from snapshot as soon as possible.", "urgent", "negative"),
    ("Cloud", "Requesting restore of test database snapshot",
     "Would like to restore our test database to last week's snapshot for a rollback "
     "test. Whenever works for your team.", "low", "positive"),
    ("Cloud", "Got a cost alert, spend jumped a lot",
     "We received a billing alert overnight - our monthly spend jumped significantly "
     "compared to normal. Want to understand why before it gets worse.", "high", "negative"),
    ("Cloud", "Question about a cost anomaly alert",
     "Saw a cost anomaly notification for our project, want to check if it's expected "
     "before I do anything about it.", "medium", "neutral"),
    ("Cloud", "Can't log into cloud console via SSO",
     "SSO login to the cloud console keeps failing for me this morning, redirects back to "
     "login every time. Need access for an incident I'm working.", "urgent", "negative"),
    ("Cloud", "SSO login issue to console",
     "Having trouble logging into the cloud console via SSO today, not blocking anything "
     "critical right now.", "medium", "neutral"),
    ("Cloud", "Instances marked unhealthy, service degraded",
     "Our load balancer is marking several backend instances unhealthy and we're seeing "
     "intermittent failures for users right now.", "urgent", "negative"),
    ("Cloud", "One target flapping health checks",
     "Noticed one of our targets flapping between healthy and unhealthy periodically. "
     "Service still up overall, just wanted to flag.", "medium", "neutral"),
    ("Cloud", "App throwing DB connection timeouts",
     "Our application has started throwing database connection timeout errors "
     "intermittently for the past hour, customers are noticing.", "urgent", "negative"),
    ("Cloud", "Occasional DB timeout in logs",
     "Seeing occasional connection timeout entries in our logs, doesn't seem to be "
     "affecting users yet but wanted to get ahead of it.", "medium", "neutral"),
    ("Cloud", "Question about how long logs are retained",
     "Trying to understand our current retention policy on the logs bucket before I "
     "document it for a compliance review. Not urgent.", "low", "neutral"),
    ("Cloud", "Need retention policy changed on archive bucket",
     "We need the retention period extended on our archive bucket per a new legal hold "
     "requirement, this needs to happen soon.", "high", "negative"),
    ("Cloud", "Requesting new dev environment for project Atlas",
     "Kicking off project Atlas next sprint and would like a new dev environment "
     "provisioned when convenient.", "low", "positive"),
    ("Cloud", "Staging environment needed urgently for demo",
     "We have a client demo in two days and need a staging environment set up. Sorry for "
     "the short notice.", "high", "negative"),
    ("Cloud", "Cert expiry warning on api.company.com",
     "Got a monitoring alert that our API certificate expires in a few days, want to get "
     "ahead of it before it causes an outage.", "high", "neutral"),
    ("Cloud", "Certificate already expired, site down",
     "Our customer portal just went down and browsers are showing a certificate expired "
     "error. This needs immediate attention.", "urgent", "negative"),
    # --- HR ---
    ("HR", "How many vacation days do I get?",
     "I'm trying to plan a trip next year and wanted to confirm how many annual leave "
     "days I'm entitled to. No rush.", "low", "positive"),
    ("HR", "Question about sick leave documentation",
     "Was out sick for 4 days last week and want to make sure I know what documentation "
     "I need to submit.", "medium", "neutral"),
    ("HR", "How do I submit a leave request?",
     "First time requesting time off here, could someone point me to how to submit a "
     "leave request in the portal?", "low", "positive"),
    ("HR", "Manager hasn't approved my leave request",
     "Submitted my leave request over a week ago and it's still pending, my trip is "
     "coming up soon and I'm getting a bit anxious about it.", "high", "negative"),
    ("HR", "Can't find this month's payslip",
     "I can't seem to find my payslip for this month in the portal, could someone check "
     "if it's been published?", "medium", "neutral"),
    ("HR", "Missing pay from this month",
     "I don't see my expected pay reflected and I'm worried something went wrong with "
     "this month's payroll run. This is pretty urgent for me.", "urgent", "negative"),
    ("HR", "Can I still enroll in benefits?",
     "I think I missed the open enrollment window, is there any way to still enroll or "
     "do I need to wait until next year?", "medium", "neutral"),
    ("HR", "Just had a baby, need to update benefits",
     "We just welcomed a new baby and I understand I can update my benefits due to this "
     "life event. Happy to send documentation.", "medium", "positive"),
    ("HR", "New hire starting Monday, access not set up",
     "I have a new hire starting Monday and I don't think their access/equipment request "
     "went through yet. Can we get this sorted before then?", "high", "negative"),
    ("HR", "Question about onboarding steps for new hire",
     "Wanted to double check what steps I need to complete before my new report's start "
     "date next month.", "low", "neutral"),
    ("HR", "Missed this week's timesheet deadline",
     "I completely forgot to submit my timesheet before the Friday cutoff, is there "
     "still a way to get it in for this pay period?", "medium", "negative"),
    ("HR", "Question on timesheet approval process",
     "Just want to confirm - does my manager need to approve my timesheet before Friday "
     "for it to count this cycle?", "low", "neutral"),
    ("HR", "Requesting temporary full remote arrangement",
     "I have a personal situation that would require me to work fully remote for about "
     "a month. Wanted to check the process for requesting this.", "medium", "neutral"),
    ("HR", "Confused about required office days",
     "Not totally sure how many in-office days are required for my role, could someone "
     "clarify? Thanks!", "low", "positive"),
    ("HR", "Expense claim rejected, not sure why",
     "My expense claim from last month got rejected and I don't understand the reason "
     "given. Can someone help me figure out what's missing?", "medium", "negative"),
    ("HR", "When will my expense reimbursement arrive?",
     "Submitted and got approval on a travel expense claim a couple weeks back, just "
     "checking on when reimbursement typically comes through.", "low", "neutral"),
    ("HR", "When does the review cycle start?",
     "Wanted to get a sense of the timeline for this year's performance review cycle so "
     "I can prepare my self-assessment.", "low", "positive"),
    ("HR", "Haven't received my review results",
     "The review cycle was supposed to wrap up a while ago and I still haven't heard "
     "anything about my results. A bit concerning.", "medium", "negative"),
    ("HR", "Question about my notice period",
     "I'm considering resigning soon and want to understand my exact notice period "
     "before I have the conversation with my manager.", "low", "neutral"),
    ("HR", "Submitted resignation, need offboarding info",
     "I submitted my resignation to my manager yesterday and wanted to check what "
     "happens next in terms of offboarding.", "medium", "neutral"),
    ("HR", "Where can I find this year's holiday calendar?",
     "Trying to plan some time around the holidays, where can I find the official "
     "company holiday calendar for this year?", "low", "positive"),
    ("HR", "Is next Monday a company holiday?",
     "Not sure if next Monday is an observed holiday for our office or not, could "
     "someone confirm quickly?", "low", "neutral"),
    ("HR", "How do I file an insurance claim?",
     "I had an out-of-network doctor visit and need to file a claim for reimbursement. "
     "Not sure of the process, could you point me in the right direction?", "medium", "neutral"),
    ("HR", "Insurance claim stuck for weeks",
     "I filed a claim almost a month ago and haven't heard anything back, and the "
     "carrier's site just shows it as pending. Getting frustrated with the wait.",
     "high", "negative"),
]


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


async def get_or_create_bulk_import_user(conn: asyncpg.Connection) -> UUID:
    user_id = await conn.fetchval("SELECT id FROM users WHERE email = $1", BULK_IMPORT_EMAIL)
    if user_id:
        return user_id
    return await conn.fetchval(
        """
        INSERT INTO users (email, full_name, role, hashed_password)
        VALUES ($1, 'Synthetic Ticket Set', 'end_user', 'CHANGE_ME_dev_placeholder')
        RETURNING id
        """,
        BULK_IMPORT_EMAIL,
    )


async def get_department_ids(conn: asyncpg.Connection) -> dict[str, UUID]:
    rows = await conn.fetch("SELECT id, name FROM departments")
    ids = {row["name"]: row["id"] for row in rows}
    needed = {dept for dept, *_ in TICKETS}
    missing = needed - set(ids)
    if missing:
        raise SystemExit(
            f"Departments missing from the database: {sorted(missing)}. "
            "Run db/seed/seed.sql first (uv run python ../db/seed/run_seed.py)."
        )
    return ids


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="Delete previously inserted synthetic tickets first"
    )
    args = parser.parse_args()

    env = dotenv_values(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set — copy .env.example to .env first.")

    conn = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        bulk_user_id = await get_or_create_bulk_import_user(conn)
        department_ids = await get_department_ids(conn)
        tenant_id = await conn.fetchval("SELECT id FROM organizations WHERE slug='ticketsense-demo'")

        existing = await conn.fetchval(
            "SELECT count(*) FROM tickets WHERE submitted_by = $1", bulk_user_id
        )
        if existing and not args.reset:
            print(
                f"{existing} synthetic tickets already present, skipping "
                "(pass --reset to replace them)."
            )
            return

        async with conn.transaction():
            if existing:
                await conn.execute("DELETE FROM tickets WHERE submitted_by = $1", bulk_user_id)
                print(f"--reset: removed {existing} previously inserted synthetic tickets.")

            await conn.executemany(
                """
                INSERT INTO tickets
                    (submitted_by, department_id, subject, description, priority, sentiment, tenant_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                [
                    (bulk_user_id, department_ids[dept], subject, description, priority, sentiment, tenant_id)
                    for dept, subject, description, priority, sentiment in TICKETS
                ],
            )
        print(f"Inserted {len(TICKETS)} synthetic labeled tickets.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
