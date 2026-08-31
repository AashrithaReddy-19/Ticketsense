"""Applies db/seed/seed.sql to the database configured in the repo-root .env.

Usage (from backend/, so the uv-managed venv has asyncpg/python-dotenv installed):
    uv run python ../db/seed/run_seed.py
"""

import asyncio
import os
import re
from pathlib import Path

import asyncpg
import bcrypt
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SEED_SQL = Path(__file__).resolve().parent / "seed.sql"


def _asyncpg_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


async def main() -> None:
    env = dotenv_values(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set — copy .env.example to .env first.")

    sql = SEED_SQL.read_text(encoding="utf-8")
    conn = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        await conn.execute(sql)
        tenant_id = await conn.fetchval("SELECT id FROM organizations WHERE slug='ticketsense-demo'")
        await conn.execute("UPDATE departments SET tenant_id=$1 WHERE tenant_id IS NULL", tenant_id)
        support_department_id = await conn.fetchval("SELECT id FROM departments WHERE name='Networking' LIMIT 1")
        demo_password = bcrypt.hashpw(b"Demo@123", bcrypt.gensalt()).decode("utf-8")
        for email, name, role in (
            ("customer@demo.com", "Customer", "customer"),
            ("agent@demo.com", "Support Agent", "support_agent"),
            ("reviewer@demo.com", "Senior Reviewer", "reviewer"),
            ("auditor@demo.com", "Compliance Auditor", "auditor"),
            ("teamlead@demo.com", "Team Lead", "team_lead"),
            ("sysadmin@demo.com", "System Administrator", "system_admin"),
            ("kbmanager@demo.com", "Knowledge Manager", "knowledge_manager"),
            ("manager@demo.com", "Team Manager", "manager"),
            ("admin@demo.com", "Enterprise Administrator", "enterprise_admin"),
            ("aiadmin@demo.com", "AI Administrator", "ai_admin"),
            ("knowledge@demo.com", "Knowledge Manager", "knowledge_manager"),
            ("security@demo.com", "Security Administrator", "security_admin"),
        ):
            await conn.execute(
                """INSERT INTO users (email, full_name, role, hashed_password, tenant_id, department_id)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (email) DO UPDATE SET full_name=EXCLUDED.full_name, hashed_password=EXCLUDED.hashed_password, role=EXCLUDED.role, tenant_id=EXCLUDED.tenant_id, department_id=EXCLUDED.department_id""",
                email, name, role, demo_password, tenant_id, support_department_id if role in {"support_agent","reviewer","team_lead","knowledge_manager"} else None,
            )
        await conn.execute("""INSERT INTO user_roles(user_id,role_id,tenant_id,department_id)
          SELECT u.id,r.id,u.tenant_id,u.department_id FROM users u JOIN roles r ON r.name=CASE
           WHEN u.role='manager' THEN 'team_lead' WHEN u.role='enterprise_admin' THEN 'system_admin'
           WHEN u.role='security_admin' THEN 'auditor' ELSE u.role END WHERE u.tenant_id=$1
          ON CONFLICT(user_id,role_id,tenant_id) DO UPDATE SET department_id=EXCLUDED.department_id""", tenant_id)
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM incidents WHERE tenant_id=$1)", tenant_id):
            await conn.execute("""INSERT INTO incidents(tenant_id,title,service,status,severity,ticket_count,growth_rate,common_symptom) VALUES
              ($1,'VPN authentication failures','VPN Authentication','investigating','critical',47,420,'Authentication timeout'),
              ($1,'Cloud storage latency','Object Storage','monitoring','high',18,138,'Intermittent high latency')""", tenant_id)
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM integrations WHERE tenant_id=$1)", tenant_id):
            for provider in ("email", "slack", "microsoft_teams", "github", "jira", "servicenow", "webhook"):
                await conn.execute("INSERT INTO integrations(tenant_id,provider,name,enabled) VALUES($1,$2,$3,false)", tenant_id, provider, provider.replace('_',' ').title())
    finally:
        await conn.close()

    print("Seed data applied.")


if __name__ == "__main__":
    asyncio.run(main())
