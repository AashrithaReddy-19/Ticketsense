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
        department_ids = {row["name"]: row["id"] for row in await conn.fetch("SELECT id,name FROM departments WHERE tenant_id=$1", tenant_id)}
        demo_password = bcrypt.hashpw(b"Demo@123", bcrypt.gensalt()).decode("utf-8")
        accounts = (
            ("customer@demo.com", "Demo Customer", "customer", None, []),
            ("agent@demo.com", "Priya VPN Engineer", "support_agent", "Networking", [("VPN Engineer", "expert", True), ("Network Engineer", "advanced", False)]),
            ("sap.engineer@demo.com", "Arjun SAP Engineer", "support_agent", "SAP", [("SAP Engineer", "expert", True)]),
            ("payment.engineer@demo.com", "Meera Payment Engineer", "support_agent", "Payments", [("Payment Engineer", "expert", True)]),
            ("network.engineer@demo.com", "Dev Network Engineer", "support_agent", "Networking", [("Network Engineer", "advanced", True)]),
            ("hr.engineer@demo.com", "Kavya HR Systems Engineer", "support_agent", "HR", [("HR Systems Engineer", "advanced", True)]),
            ("cloud.engineer@demo.com", "Rahul Cloud Engineer", "support_agent", "Cloud", [("Cloud Engineer", "expert", True)]),
            ("general.engineer@demo.com", "Nisha General Support Engineer", "support_agent", "Networking", [("General Support Engineer", "intermediate", True)]),
            ("reviewer@demo.com", "Senior Reviewer", "reviewer", "Networking", []),
            ("auditor@demo.com", "Compliance Auditor", "auditor", None, []),
            ("teamlead@demo.com", "Team Lead", "team_lead", "Networking", []),
            ("sysadmin@demo.com", "TicketSense Administrator", "system_admin", None, []),
            ("kbmanager@demo.com", "Knowledge Manager", "knowledge_manager", "Networking", []),
            ("manager@demo.com", "Team Manager", "manager", "Networking", []),
            ("admin@demo.com", "Enterprise Administrator", "enterprise_admin", None, []),
            ("aiadmin@demo.com", "AI Administrator", "ai_admin", None, []),
            ("knowledge@demo.com", "Knowledge Manager", "knowledge_manager", "Networking", []),
            ("security@demo.com", "Security Administrator", "security_admin", None, []),
        )
        for email, name, role, department_name, skills in accounts:
            public_role = "customer" if role in {"customer", "end_user"} else "engineer" if role in {"support_agent", "department_engineer"} else "admin"
            department_id = department_ids.get(department_name) if department_name else None
            await conn.execute(
                """INSERT INTO users (email, full_name, role, public_role, hashed_password, tenant_id, department_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (email) DO UPDATE SET full_name=EXCLUDED.full_name, hashed_password=EXCLUDED.hashed_password, role=EXCLUDED.role, public_role=EXCLUDED.public_role, tenant_id=EXCLUDED.tenant_id, department_id=EXCLUDED.department_id""",
                email, name, role, public_role, demo_password, tenant_id, department_id,
            )
            if public_role == "engineer":
                user_id = await conn.fetchval("SELECT id FROM users WHERE email=$1", email)
                await conn.execute("""INSERT INTO engineer_departments(user_id,department_id)
                    VALUES($1,$2) ON CONFLICT(user_id,department_id) DO NOTHING""", user_id, department_id)
                await conn.execute("""INSERT INTO engineer_profiles(user_id,tenant_id,availability_status,max_weighted_capacity)
                    VALUES($1,$2,'available',10) ON CONFLICT(user_id) DO UPDATE SET tenant_id=EXCLUDED.tenant_id""", user_id, tenant_id)
                for specialization, level, primary in skills:
                    await conn.execute("""INSERT INTO engineer_skills(tenant_id,user_id,department_id,specialization,skill_level,is_primary)
                        VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(user_id,department_id,specialization)
                        DO UPDATE SET skill_level=EXCLUDED.skill_level,is_primary=EXCLUDED.is_primary,is_active=true""",
                        tenant_id, user_id, department_id, specialization, level, primary)
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
        admin_id = await conn.fetchval("SELECT id FROM users WHERE email='sysadmin@demo.com'")
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM department_resolution_policies WHERE tenant_id=$1)", tenant_id):
            sensitive = ["payment", "security", "access_control", "data_loss", "credential_exposure", "legal", "compliance", "critical_incident"]
            for department_name, threshold, allowlist in (
                ("Networking", .88, ["vpn", "general_it", "network"]),
                ("SAP", .85, ["sap"]),
                ("Cloud", .85, ["cloud", "general_it"]),
                ("HR", .90, ["general_it"]),
                ("Payments", .92, []),
            ):
                await conn.execute("""INSERT INTO department_resolution_policies(tenant_id,department_id,version,allow_auto_resolution,auto_resolve_threshold,minimum_citation_coverage,minimum_retrieval_score,minimum_classification_confidence,minimum_classification_margin,auto_resolution_allowlist,sensitive_category_denylist,updated_by,reason)
                  VALUES($1,$2,1,$3,$4,.8,.65,.75,.15,$5::jsonb,$6::jsonb,$7,'Deterministic demonstration policy; all safety gates remain mandatory')""",
                  tenant_id, department_ids[department_name], bool(allowlist), threshold, __import__("json").dumps(allowlist), __import__("json").dumps(sensitive), admin_id)
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM sla_policies WHERE tenant_id=$1)", tenant_id):
            for priority, response_minutes, resolution_minutes in (
                ("urgent", 15, 4 * 60), ("high", 30, 8 * 60), ("medium", 120, 24 * 60), ("low", 480, 72 * 60),
            ):
                await conn.execute(
                    "INSERT INTO sla_policies(tenant_id,name,priority,response_minutes,resolution_minutes,is_active) VALUES($1,$2,$3,$4,$5,true)",
                    tenant_id, f"{priority.title()} priority", priority, response_minutes, resolution_minutes,
                )
    finally:
        await conn.close()

    print("Seed data applied.")


if __name__ == "__main__":
    asyncio.run(main())
