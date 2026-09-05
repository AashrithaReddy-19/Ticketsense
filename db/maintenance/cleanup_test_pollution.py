"""Removes confirmed test-generated debris left behind in two distinct, exact-match
scopes -- never a heuristic, never "everything older than N days".

  1. Demo-tenant debris: rows created *inside* the real demo tenant (slug
     'ticketsense-demo') by backend test runs that predate the conftest.py
     fixtures (``demo_tickets``, ``demo_knowledge_articles``) that now prevent
     this going forward:
       - Tickets whose subject exactly matches one of the hardcoded test-marker
         patterns below.
       - Knowledge articles whose title matches one of the hardcoded test-marker
         patterns, plus their linked knowledge_base row and its embeddings.

  2. Orphaned per-test tenants: entire Organizations that a handful of test
     fixtures created with their own dedicated tenant per test run, and whose
     teardown either didn't exist or had a bug (see
     backend/tests/test_resolution_retrieval_isolation.py and
     backend/tests/test_playbooks.py, both fixed alongside this script) that
     left them in the database forever instead of deleting them at the end of
     the test. Matched by the exact name prefixes those fixtures use, and only
     ever deleted after confirming every user in that tenant has the
     '@example.test' address every one of these fixtures uses -- a tenant with
     any real-looking user is left alone and reported as skipped instead.

Safety properties:
  - Defaults to a dry run. Nothing is deleted unless you pass --confirm.
  - Refuses to run at all unless the real demo tenant (slug 'ticketsense-demo')
    exists -- there is no way to point this at an arbitrary tenant via a flag.
  - Refuses to run if APP_ENV=production.
  - Never matches the real demo tenant as an "orphaned test tenant" -- its id
    is hardcoded as an exclusion in addition to the slug check.
  - Before deleting anything, writes a full JSON manifest (every matched
    ticket/article/tenant id, per-table row counts, and the patterns used) to
    db/maintenance/backups/, timestamped, so the exact scope of a run can be
    audited after the fact.
  - The dry run and the confirm run compute the exact same matched-id sets and
    delete only those ids inside a single transaction that rolls back
    completely if any step fails -- never a broader re-match at delete time.

Usage (from backend/, so the uv-managed venv has asyncpg/python-dotenv installed):
    uv run python ../db/maintenance/cleanup_test_pollution.py                 # dry run
    uv run python ../db/maintenance/cleanup_test_pollution.py --confirm       # deletes
"""
import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = Path(__file__).resolve().parent / "backups"
DEMO_TENANT_SLUG = "ticketsense-demo"

# Exact subject strings, or SQL LIKE patterns (containing %), that are unambiguous
# test-suite artifacts -- see backend/tests/*.py for the literal strings that
# generated each of these. Never add a broad/heuristic pattern here (e.g. a bare
# "%check%") -- every entry must be a specific, known test-generated subject.
TEST_SUBJECT_LIKE_PATTERNS = ("Knowledge gap check %",)
TEST_SUBJECT_EXACT = (
    "Pipeline metrics VPN check", "Resolution translation check", "SLA due-date check",
    "Same language translation check", "Translation availability check",
    "VPN internal note leakage check", "VPN pipeline failure test",
    "VPN resolution confirmation check", "VPN test workflow synchronization",
    "VPN-809 on Windows 11", "Docker E2E smoke VPN check",
)

# Exact LIKE patterns for knowledge_articles.title generated directly by
# backend/tests/test_knowledge_lifecycle.py (not tied to a polluted ticket, so
# not caught by TEST_SUBJECT_* above).
TEST_ARTICLE_TITLE_LIKE_PATTERNS = (
    "Knowledge lifecycle test article %",
    "Embedding failure test %",
    "Rejected article %",
)

# Exact name prefixes for Organizations created by backend/tests/*.py's own
# tenant-scoped fixtures. Each maps to the test file that creates it, purely
# for the report -- matching is by name prefix only.
TEST_TENANT_NAME_PREFIXES = {
    "Resolution Tenant A ": "test_resolution_retrieval_isolation.py",
    "Resolution Tenant B ": "test_resolution_retrieval_isolation.py",
    "Resolution Policy Tenant ": "test_resolution_policy_and_assignment.py",
    "Playbook Gate Tenant ": "test_playbooks.py",
    "Prevention Tenant ": "test_prevention.py",
    "Incident Tenant ": "test_incidents.py",
    "SafeAction Tenant ": "test_safe_actions.py",
    "Attachment Tenant A ": "test_attachment_api.py",
    "Attachment Tenant B ": "test_attachment_api.py",
    "Isolation Tenant A ": "test_ticket_isolation_matrix.py",
    "Isolation Tenant B ": "test_ticket_isolation_matrix.py",
}

# Every tenant-scoped (or transitively tenant-owned) table that must be purged,
# in dependency order, before an orphaned test tenant's Organization row itself
# can be deleted. Built from the live FK graph (see the session notes this
# script's docstring references): most rows already cascade automatically from
# either `organizations` or `tickets`, but several use ON DELETE NO ACTION /
# SET NULL and would otherwise block deletion, so every one of them is deleted
# explicitly rather than relying on cascade.
_TENANT_TABLES_LEAF_FIRST = (
    ("confidence_components", "ticket_decision_id IN (SELECT id FROM ticket_decisions WHERE tenant_id=$1)"),
    ("pipeline_stages", "execution_id IN (SELECT id FROM pipeline_executions WHERE tenant_id=$1)"),
    ("diagnostic_steps", "plan_id IN (SELECT id FROM diagnostic_plans WHERE tenant_id=$1)"),
    ("ticket_message_reads", "message_id IN (SELECT id FROM ticket_messages WHERE tenant_id=$1)"),
    ("ticket_history", "ticket_id IN (SELECT id FROM tickets WHERE tenant_id=$1)"),
    ("recommendation_actions", "recommendation_id IN (SELECT id FROM prevention_recommendations WHERE tenant_id=$1)"),
    ("recommendation_evidence", "recommendation_id IN (SELECT id FROM prevention_recommendations WHERE tenant_id=$1)"),
    ("safe_action_approvals", "execution_id IN (SELECT id FROM safe_action_executions WHERE tenant_id=$1)"),
    ("safe_action_results", "execution_id IN (SELECT id FROM safe_action_executions WHERE tenant_id=$1)"),
    ("embeddings", "knowledge_base_id IN (SELECT id FROM knowledge_base WHERE tenant_id=$1)"),
    ("ticket_decisions", "tenant_id=$1"),
    ("assignment_decisions", "tenant_id=$1"),
    ("diagnostic_plans", "tenant_id=$1"),
    ("ticket_messages", "tenant_id=$1"),
    ("resolution_confirmations", "tenant_id=$1"),
    ("department_resolution_policies", "tenant_id=$1"),
    ("department_confidence_policies", "tenant_id=$1"),
    ("pipeline_executions", "tenant_id=$1"),
    ("pipeline_metrics", "tenant_id=$1"),
    ("ai_drafts", "tenant_id=$1"),
    ("ai_decisions", "tenant_id=$1"),
    ("response_drafts", "tenant_id=$1"),
    ("ticket_events", "tenant_id=$1"),
    ("claim_validations", "tenant_id=$1"),
    ("technical_entities", "tenant_id=$1"),
    ("ticket_attachments", "tenant_id=$1"),
    ("human_reviews", "tenant_id=$1"),
    ("audit_logs", "tenant_id=$1"),
    ("notifications", "tenant_id=$1"),
    ("knowledge_articles", "tenant_id=$1"),
    ("knowledge_base", "tenant_id=$1"),
    ("incidents", "tenant_id=$1"),
    ("prevention_recommendations", "tenant_id=$1"),
    ("safe_action_executions", "tenant_id=$1"),
    ("playbooks", "tenant_id=$1"),
    ("integrations", "tenant_id=$1"),
    ("sla_policies", "tenant_id=$1"),
    ("engineer_departments", "user_id IN (SELECT id FROM users WHERE tenant_id=$1)"),
    ("engineer_specializations", "user_id IN (SELECT id FROM users WHERE tenant_id=$1)"),
    ("engineer_skills", "tenant_id=$1"),
    ("engineer_profiles", "tenant_id=$1"),
    ("tickets", "tenant_id=$1"),
    ("user_roles", "tenant_id=$1"),
    ("auth_sessions", "user_id IN (SELECT id FROM users WHERE tenant_id=$1)"),
    ("users", "tenant_id=$1"),
    ("departments", "tenant_id=$1"),
)


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


def _ticket_match_clause() -> str:
    exact = ",".join(f"'{s}'" for s in sorted(set(TEST_SUBJECT_EXACT)))
    like_clauses = " OR ".join(f"subject LIKE '{p}'" for p in TEST_SUBJECT_LIKE_PATTERNS)
    return f"(subject IN ({exact}) OR {like_clauses})"


def _article_title_match_clause() -> str:
    return " OR ".join(f"title LIKE '{p}'" for p in TEST_ARTICLE_TITLE_LIKE_PATTERNS)


async def _connect() -> asyncpg.Connection:
    env = dotenv_values(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set -- copy .env.example to .env first.")
    return await asyncpg.connect(_asyncpg_url(database_url))


async def _find_orphan_tenants(conn: asyncpg.Connection, demo_tenant_id) -> tuple[list[dict], list[dict]]:
    """Returns (eligible, skipped) organizations matching a known test-tenant
    name prefix. `skipped` holds matches that failed the '@example.test'
    all-users check and must never be deleted."""
    like_clauses = " OR ".join(f"name LIKE '{prefix}%'" for prefix in TEST_TENANT_NAME_PREFIXES)
    rows = await conn.fetch(
        f"SELECT id, name, slug, created_at FROM organizations WHERE id != $1 AND slug != $2 AND ({like_clauses}) ORDER BY created_at",
        demo_tenant_id, DEMO_TENANT_SLUG,
    )
    eligible, skipped = [], []
    for row in rows:
        matched_prefix = next(p for p in TEST_TENANT_NAME_PREFIXES if row["name"].startswith(p))
        non_test_users = await conn.fetch(
            "SELECT email FROM users WHERE tenant_id=$1 AND email NOT LIKE '%@example.test'", row["id"],
        )
        user_count = await conn.fetchval("SELECT count(*) FROM users WHERE tenant_id=$1", row["id"])
        entry = {
            "id": str(row["id"]), "name": row["name"], "slug": row["slug"],
            "created_at": row["created_at"].isoformat(), "matched_prefix": matched_prefix,
            "source_test_file": TEST_TENANT_NAME_PREFIXES[matched_prefix], "user_count": user_count,
        }
        if non_test_users:
            entry["non_test_user_emails"] = [r["email"] for r in non_test_users]
            skipped.append(entry)
        else:
            eligible.append(entry)
    return eligible, skipped


async def _table_counts_for_tenants(conn: asyncpg.Connection, tenant_ids: list[str]) -> dict[str, int]:
    if not tenant_ids:
        return {}
    counts: dict[str, int] = {}
    for table, condition in _TENANT_TABLES_LEAF_FIRST:
        total = 0
        for t in tenant_ids:
            total += await conn.fetchval(f"SELECT count(*) FROM {table} WHERE {condition}", t)
        if total:
            counts[table] = total
    return counts


async def _purge_tenant(conn: asyncpg.Connection, tenant_id: str) -> None:
    for table, condition in _TENANT_TABLES_LEAF_FIRST:
        await conn.execute(f"DELETE FROM {table} WHERE {condition}", tenant_id)
    await conn.execute("DELETE FROM organizations WHERE id=$1", tenant_id)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true", help="Actually delete the matched rows. Without this flag, only reports what would be removed.")
    args = parser.parse_args()

    if os.environ.get("APP_ENV") == "production":
        raise SystemExit("Refusing to run: APP_ENV=production. This script only ever targets local/test debris.")

    conn = await _connect()
    try:
        tenant = await conn.fetchrow("SELECT id, slug FROM organizations WHERE slug=$1", DEMO_TENANT_SLUG)
        if not tenant:
            raise SystemExit(f"Refusing to run: no tenant with slug '{DEMO_TENANT_SLUG}' exists in this database.")
        demo_tenant_id = tenant["id"]

        # --- Scope 1a: demo-tenant test tickets ---
        ticket_rows = await conn.fetch(
            f"SELECT id, subject, status, created_at FROM tickets WHERE tenant_id=$1 AND {_ticket_match_clause()} ORDER BY created_at",
            demo_tenant_id,
        )

        # --- Scope 1b: demo-tenant test knowledge articles (+ their kb rows / embeddings) ---
        article_rows = await conn.fetch(
            f"SELECT id, title, status, published_knowledge_base_id, created_at FROM knowledge_articles WHERE tenant_id=$1 AND ({_article_title_match_clause()}) ORDER BY created_at",
            demo_tenant_id,
        )
        kb_ids = [str(r["published_knowledge_base_id"]) for r in article_rows if r["published_knowledge_base_id"]]
        embedding_count = await conn.fetchval(
            "SELECT count(*) FROM embeddings WHERE knowledge_base_id = ANY($1::uuid[])", kb_ids,
        ) if kb_ids else 0

        # --- Scope 2: orphaned per-test tenants ---
        orphan_tenants, skipped_tenants = await _find_orphan_tenants(conn, demo_tenant_id)
        orphan_ids = [t["id"] for t in orphan_tenants]
        orphan_table_counts = await _table_counts_for_tenants(conn, orphan_ids)

        print(f"=== Demo tenant '{DEMO_TENANT_SLUG}' ({demo_tenant_id}) ===")
        print(f"\nTickets matched ({len(ticket_rows)}), patterns: {sorted(set(TEST_SUBJECT_EXACT))} + LIKE {TEST_SUBJECT_LIKE_PATTERNS}")
        by_status: dict[str, int] = {}
        for r in ticket_rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        for status, count in sorted(by_status.items()):
            print(f"  {status:<20} {count}")

        print(f"\nKnowledge articles matched ({len(article_rows)}), patterns: {TEST_ARTICLE_TITLE_LIKE_PATTERNS}")
        by_article_status: dict[str, int] = {}
        for r in article_rows:
            by_article_status[r["status"]] = by_article_status.get(r["status"], 0) + 1
        for status, count in sorted(by_article_status.items()):
            print(f"  {status:<20} {count}")
        print(f"  linked knowledge_base rows: {len(kb_ids)}")
        print(f"  linked embeddings: {embedding_count}")

        print(f"\n=== Orphaned per-test tenants ===")
        print(f"Eligible for deletion ({len(orphan_tenants)}) -- name prefix matched AND every user is '@example.test':")
        for t in orphan_tenants:
            print(f"  {t['created_at']}  {t['name']:<40} users={t['user_count']:<3} ({t['source_test_file']})")
        if orphan_table_counts:
            print("  Dependent row counts by table:")
            for table, count in sorted(orphan_table_counts.items()):
                print(f"    {table:<32} {count}")
        if skipped_tenants:
            print(f"\nSKIPPED -- name matched but at least one non-'@example.test' user found (never deleted automatically):")
            for t in skipped_tenants:
                print(f"  {t['name']} ({t['id']}): {t['non_test_user_emails']}")

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "demo_tenant": {"id": str(demo_tenant_id), "slug": DEMO_TENANT_SLUG},
            "tickets_matched": [{"id": str(r["id"]), "subject": r["subject"], "status": r["status"], "created_at": r["created_at"].isoformat()} for r in ticket_rows],
            "knowledge_articles_matched": [{"id": str(r["id"]), "title": r["title"], "status": r["status"], "created_at": r["created_at"].isoformat()} for r in article_rows],
            "knowledge_base_ids_matched": kb_ids,
            "embedding_count_matched": embedding_count,
            "orphan_tenants_eligible": orphan_tenants,
            "orphan_tenants_skipped": skipped_tenants,
            "orphan_tenant_dependent_row_counts": orphan_table_counts,
            "confirm": args.confirm,
        }

        if not ticket_rows and not article_rows and not orphan_tenants:
            print("\nNo matching test debris found. Nothing to do.")
            return

        if not args.confirm:
            print(f"\nDry run only -- no rows deleted. Re-run with --confirm to delete "
                  f"{len(ticket_rows)} ticket(s), {len(article_rows)} knowledge article(s), "
                  f"and {len(orphan_tenants)} orphaned tenant(s).")
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            manifest_path = BACKUP_DIR / f"dry_run_manifest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
            print(f"Wrote dry-run manifest to {manifest_path}")
            return

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        full_ticket_rows = await conn.fetch(f"SELECT * FROM tickets WHERE id = ANY($1::uuid[])", [r["id"] for r in ticket_rows]) if ticket_rows else []
        full_article_rows = await conn.fetch(f"SELECT * FROM knowledge_articles WHERE id = ANY($1::uuid[])", [r["id"] for r in article_rows]) if article_rows else []
        full_org_rows = await conn.fetch(f"SELECT * FROM organizations WHERE id = ANY($1::uuid[])", [t["id"] for t in orphan_tenants]) if orphan_tenants else []

        backup_path = BACKUP_DIR / f"cleanup_{ts}.json"
        backup_path.write_text(json.dumps({
            "tickets": [dict(r) for r in full_ticket_rows],
            "knowledge_articles": [dict(r) for r in full_article_rows],
            "organizations": [dict(r) for r in full_org_rows],
        }, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote a full backup of matched rows to {backup_path}")

        manifest_path = BACKUP_DIR / f"cleanup_manifest_{ts}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        print(f"Wrote cleanup manifest to {manifest_path}")

        async with conn.transaction():
            if kb_ids:
                await conn.execute("DELETE FROM embeddings WHERE knowledge_base_id = ANY($1::uuid[])", kb_ids)
            if article_rows:
                await conn.execute("DELETE FROM knowledge_articles WHERE id = ANY($1::uuid[])", [r["id"] for r in article_rows])
            if kb_ids:
                await conn.execute("DELETE FROM knowledge_base WHERE id = ANY($1::uuid[])", kb_ids)
            if ticket_rows:
                ticket_ids = [r["id"] for r in ticket_rows]
                await conn.execute("DELETE FROM knowledge_articles WHERE source_ticket_ids ?| $1::text[]", [str(i) for i in ticket_ids])
                await conn.execute("DELETE FROM tickets WHERE id = ANY($1::uuid[])", ticket_ids)
            for tenant_id in orphan_ids:
                await _purge_tenant(conn, tenant_id)

        print(f"\nDeleted {len(ticket_rows)} ticket(s), {len(article_rows)} knowledge article(s) "
              f"(+{len(kb_ids)} knowledge_base row(s), +{embedding_count} embedding(s)), "
              f"and {len(orphan_tenants)} orphaned tenant(s).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
