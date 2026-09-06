"""Ensures the versioned suite/case catalog exists, then executes every case
function for a real run and persists the results. Never inserts anything
into the production knowledge corpus and never sends anything to a
customer — see cases.py for what each case actually does.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.red_team import RedTeamCase, RedTeamResult, RedTeamRun, RedTeamSuite
from app.services.red_team.cases import CASES, SUITE_DESCRIPTION, SUITE_KEY, SUITE_NAME, SUITE_VERSION


async def ensure_suite_seeded(db: AsyncSession) -> RedTeamSuite:
    suite = await db.scalar(select(RedTeamSuite).where(RedTeamSuite.suite_key == SUITE_KEY, RedTeamSuite.version == SUITE_VERSION))
    if not suite:
        suite = RedTeamSuite(suite_key=SUITE_KEY, name=SUITE_NAME, version=SUITE_VERSION, description=SUITE_DESCRIPTION)
        db.add(suite)
        await db.flush()
    existing_keys = set(await db.scalars(select(RedTeamCase.case_key).where(RedTeamCase.suite_id == suite.id)))
    for definition, _ in CASES:
        if definition.case_key in existing_keys:
            continue
        db.add(RedTeamCase(
            suite_id=suite.id, case_key=definition.case_key, category=definition.category, severity=definition.severity,
            title=definition.title, description=definition.description, expected_result=definition.expected_result,
        ))
    await db.flush()
    return suite


async def run_suite(db: AsyncSession, tenant_id, triggered_by) -> RedTeamRun:
    suite = await ensure_suite_seeded(db)
    case_rows = {row.case_key: row for row in (await db.scalars(select(RedTeamCase).where(RedTeamCase.suite_id == suite.id))).all()}

    started_at = datetime.now(timezone.utc)
    run = RedTeamRun(tenant_id=tenant_id, suite_id=suite.id, suite_version=suite.version, status="completed", started_at=started_at, triggered_by=triggered_by)
    db.add(run)
    await db.flush()

    for definition, case_fn in CASES:
        case_row = case_rows[definition.case_key]
        try:
            outcome = await case_fn(db, tenant_id)
        except Exception as exc:  # a case crashing is itself a finding, never a silent skip
            db.add(RedTeamResult(
                run_id=run.id, case_id=case_row.id, observed_result="error", passed=False, applicable=True,
                gate_responsible=None, detail=f"Case raised an unexpected exception: {type(exc).__name__}: {exc}", evidence={},
            ))
            continue
        db.add(RedTeamResult(
            run_id=run.id, case_id=case_row.id, observed_result=outcome.observed_result, passed=outcome.passed,
            applicable=outcome.applicable, gate_responsible=outcome.gate_responsible, detail=outcome.detail, evidence=outcome.evidence,
        ))

    run.completed_at = datetime.now(timezone.utc)
    await db.flush()
    return run


async def summarize_run(db: AsyncSession, run: RedTeamRun) -> dict:
    results = (await db.scalars(select(RedTeamResult).where(RedTeamResult.run_id == run.id))).all()
    case_rows = {row.id: row for row in (await db.scalars(select(RedTeamCase).where(RedTeamCase.id.in_([r.case_id for r in results])))).all()}

    applicable = [r for r in results if r.applicable]
    failed = [r for r in applicable if not r.passed]
    by_category: dict[str, dict] = {}
    by_severity: dict[str, dict] = {}
    for result in results:
        case = case_rows[result.case_id]
        bucket = by_category.setdefault(case.category, {"total": 0, "failed": 0})
        bucket["total"] += 1
        if result.applicable and not result.passed:
            bucket["failed"] += 1
        sev_bucket = by_severity.setdefault(case.severity, {"total": 0, "failed": 0})
        sev_bucket["total"] += 1
        if result.applicable and not result.passed:
            sev_bucket["failed"] += 1

    return {
        "run_id": run.id, "suite_version": run.suite_version, "status": run.status,
        "started_at": run.started_at, "completed_at": run.completed_at,
        "total_cases": len(results), "applicable_cases": len(applicable), "not_applicable_cases": len(results) - len(applicable),
        "attack_success_rate": round(len(failed) / len(applicable), 4) if applicable else None,
        "block_rate": round((len(applicable) - len(failed)) / len(applicable), 4) if applicable else None,
        "by_category": by_category, "by_severity": by_severity,
        "results": [{
            "case_key": case_rows[r.case_id].case_key, "category": case_rows[r.case_id].category, "severity": case_rows[r.case_id].severity,
            "title": case_rows[r.case_id].title, "expected_result": case_rows[r.case_id].expected_result,
            "observed_result": r.observed_result, "passed": r.passed, "applicable": r.applicable,
            "gate_responsible": r.gate_responsible, "detail": r.detail,
        } for r in results],
    }
