"""Removes confirmed test-generated tickets from the demo tenant.

Repeated backend test-suite runs against the seeded demo tenant (customer@demo.com,
etc.) can leave real, committed ticket rows behind when a test doesn't clean up after
itself (see backend/tests/conftest.py:demo_tickets for the fixture that now prevents
this going forward for every test that creates a demo-tenant ticket). This script is
the manual remedy for pollution that already happened before that fixture existed.

Safety properties:
  - Defaults to a dry run. Nothing is deleted unless you pass --confirm.
  - Only ever targets rows whose subject exactly matches one of the hardcoded,
    unambiguous test-marker patterns below -- never a heuristic, never "everything
    older than N days", never a customer's genuine ticket.
  - Refuses to run at all unless the target tenant's slug is exactly
    "ticketsense-demo" (the seeded demo/local-dev tenant) -- there is no way to point
    this at an arbitrary tenant via a flag.
  - Refuses to run if APP_ENV=production.
  - Before deleting anything, writes a full JSON backup of every matched ticket row
    (and its immediate identifying fields) to db/maintenance/backups/, timestamped,
    so a mistaken match can be manually restored/audited after the fact.

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
    "Resolution translation check", "Translation availability check",
)


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


def _match_clause() -> str:
    exact = ",".join(f"'{s}'" for s in sorted(set(TEST_SUBJECT_EXACT)))
    like_clauses = " OR ".join(f"subject LIKE '{p}'" for p in TEST_SUBJECT_LIKE_PATTERNS)
    return f"(subject IN ({exact}) OR {like_clauses})"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true", help="Actually delete the matched tickets. Without this flag, only lists what would be removed.")
    args = parser.parse_args()

    if os.environ.get("APP_ENV") == "production":
        raise SystemExit("Refusing to run: APP_ENV=production. This script only ever targets the local/demo tenant.")

    env = dotenv_values(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set -- copy .env.example to .env first.")

    conn = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        tenant = await conn.fetchrow("SELECT id, slug FROM organizations WHERE slug=$1", DEMO_TENANT_SLUG)
        if not tenant:
            raise SystemExit(f"Refusing to run: no tenant with slug '{DEMO_TENANT_SLUG}' exists in this database.")
        tenant_id = tenant["id"]

        rows = await conn.fetch(
            f"SELECT id, subject, status, created_at FROM tickets WHERE tenant_id=$1 AND {_match_clause()} ORDER BY created_at",
            tenant_id,
        )
        if not rows:
            print("No matching test-pollution tickets found. Nothing to do.")
            return

        print(f"Matched {len(rows)} test-generated ticket(s) in tenant '{DEMO_TENANT_SLUG}':")
        for row in rows:
            print(f"  {row['created_at']}  {row['status']:<20}  {row['subject']}  ({row['id']})")

        if not args.confirm:
            print(f"\nDry run only -- no rows deleted. Re-run with --confirm to actually delete these {len(rows)} ticket(s).")
            return

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"cleanup_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        full_rows = await conn.fetch(f"SELECT * FROM tickets WHERE tenant_id=$1 AND {_match_clause()}", tenant_id)
        backup_path.write_text(json.dumps([dict(r) for r in full_rows], indent=2, default=str), encoding="utf-8")
        print(f"Wrote a full backup of {len(full_rows)} row(s) to {backup_path}")

        ids = [row["id"] for row in rows]
        await conn.execute("DELETE FROM knowledge_articles WHERE source_ticket_ids ?| $1::text[]", [str(i) for i in ids])
        deleted = await conn.execute("DELETE FROM tickets WHERE id = ANY($1::uuid[])", ids)
        print(f"Deleted: {deleted}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
