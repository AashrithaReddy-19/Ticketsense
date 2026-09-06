"""Coverage for the red-team lab (V2 Phase 9): each case must exercise a
real defense mechanism and report an honest result — including the one
case that is expected to reveal a genuine, currently-unfixed gap — the
suite/case catalog must seed idempotently, a crashing case must not abort
the whole run, and the cross-tenant probe case must never leave its
throwaway tenant behind.
"""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.security import hash_password
from app.database import async_session_maker
from app.main import app
from app.models.red_team import RedTeamCase, RedTeamResult
from app.models.user import User
from app.services.red_team import cases as case_module
from app.services.red_team.runner import ensure_suite_seeded, run_suite, summarize_run
from test_resolution_policy_and_assignment import scenario


@pytest.mark.asyncio(loop_scope="session")
async def test_fabricated_citation_case_detects_real_rejection(scenario):
    async with async_session_maker() as db:
        outcome = await case_module._fabricated_citation_rejected(db, scenario["tenant_id"])
        assert outcome.passed is True
        assert outcome.observed_result == "rejected"
        assert outcome.gate_responsible == "citation_validation"


@pytest.mark.asyncio(loop_scope="session")
async def test_contradictory_evidence_case_detects_real_block(scenario):
    async with async_session_maker() as db:
        outcome = await case_module._contradictory_evidence_blocks_resolution(db, scenario["tenant_id"])
        assert outcome.passed is True
        assert outcome.observed_result == "Conflicting Evidence"


@pytest.mark.asyncio(loop_scope="session")
async def test_unsafe_instruction_case_detects_real_flag(scenario):
    async with async_session_maker() as db:
        outcome = await case_module._unsafe_instruction_flagged(db, scenario["tenant_id"])
        assert outcome.passed is True
        assert outcome.observed_result == "Human Investigation Required"


@pytest.mark.asyncio(loop_scope="session")
async def test_path_traversal_case_detects_real_rejection(scenario):
    async with async_session_maker() as db:
        outcome = await case_module._path_traversal_filename_rejected(db, scenario["tenant_id"])
        assert outcome.passed is True
        assert outcome.observed_result == "path_traversal"


@pytest.mark.asyncio(loop_scope="session")
async def test_role_escalation_case_confirms_no_leak(scenario):
    async with async_session_maker() as db:
        outcome = await case_module._role_escalation_blocked_for_customer(db, scenario["tenant_id"])
        assert outcome.passed is True
        assert outcome.evidence["leaked"] == []


@pytest.mark.asyncio(loop_scope="session")
async def test_encoded_secret_case_honestly_reports_the_real_gap(scenario):
    """This is the one case expected to fail: base64-encoded secrets are not
    caught by the current regex-based redactor. The red-team lab must report
    this honestly rather than being tuned to always pass."""
    async with async_session_maker() as db:
        outcome = await case_module._encoded_secret_redaction_gap(db, scenario["tenant_id"])
        assert outcome.passed is False
        assert outcome.observed_result == "not_redacted"
        assert "not caught" in outcome.detail.lower() or "gap" in outcome.detail.lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_prompt_injection_case_detects_real_flag(scenario):
    async with async_session_maker() as db:
        outcome = await case_module._prompt_injection_cannot_suppress_sensitive_flag(db, scenario["tenant_id"])
        assert outcome.passed is True
        assert outcome.observed_result == "flagged"


@pytest.mark.asyncio(loop_scope="session")
async def test_system_prompt_disclosure_case_is_honestly_not_applicable(scenario):
    async with async_session_maker() as db:
        outcome = await case_module._system_prompt_disclosure_not_applicable(db, scenario["tenant_id"])
        assert outcome.applicable is False
        assert outcome.observed_result == "not_applicable"


@pytest.mark.asyncio(loop_scope="session")
async def test_cross_tenant_probe_detects_isolation_and_cleans_up_after_itself(scenario):
    before = await _organization_count()
    async with async_session_maker() as db:
        outcome = await case_module._cross_tenant_ticket_visibility_blocked(db, scenario["tenant_id"])
        await db.commit()
        assert outcome.passed is True
        assert outcome.observed_result == "isolated"
    after = await _organization_count()
    assert after == before  # the throwaway foreign tenant left no trace


async def _organization_count() -> int:
    async with async_session_maker() as db:
        return await db.scalar(text("SELECT COUNT(*) FROM organizations")) or 0


@pytest.mark.asyncio(loop_scope="session")
async def test_suite_seeding_is_idempotent(scenario):
    async with async_session_maker() as db:
        first = await ensure_suite_seeded(db)
        await db.commit()
        first_cases = list((await db.scalars(select(RedTeamCase.id).where(RedTeamCase.suite_id == first.id))).all())

        second = await ensure_suite_seeded(db)
        await db.commit()
        second_cases = list((await db.scalars(select(RedTeamCase.id).where(RedTeamCase.suite_id == second.id))).all())

        assert first.id == second.id
        assert sorted(first_cases) == sorted(second_cases)
        assert len(second_cases) == len(case_module.CASES)


@pytest.mark.asyncio(loop_scope="session")
async def test_a_crashing_case_does_not_abort_the_whole_run(monkeypatch, scenario):
    async def _boom(db, tenant_id):
        raise RuntimeError("synthetic failure for test coverage")

    original_cases = case_module.CASES
    patched = [(d, _boom if d.case_key == "fabricated_citation_rejected" else fn) for d, fn in original_cases]
    monkeypatch.setattr("app.services.red_team.runner.CASES", patched)

    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-redteam-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.commit()
        run = await run_suite(db, scenario["tenant_id"], admin_id)
        await db.commit()

        results = (await db.scalars(select(RedTeamResult).where(RedTeamResult.run_id == run.id))).all()
        assert len(results) == len(original_cases)  # every case produced a result row, including the one that crashed
        crashed = [r for r in results if r.observed_result == "error"]
        assert len(crashed) == 1
        assert crashed[0].passed is False
        assert "RuntimeError" in crashed[0].detail


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_red_team_endpoints_are_feature_flag_gated_then_return_real_results():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _login(client, "sysadmin@demo.com")
        headers = _auth(admin)
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        gated = await client.post("/api/v2/red-team/runs", headers=headers)
        assert gated.status_code == 404  # red_team_lab flag disabled by default

        override = await client.post(
            "/api/v2/features/red_team_lab/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "Red-team lab test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        try:
            run_response = await client.post("/api/v2/red-team/runs", headers=headers)
            assert run_response.status_code == 201, run_response.text
            summary = run_response.json()
            assert summary["applicable_cases"] >= 8
            assert summary["attack_success_rate"] is not None
            assert any(r["case_key"] == "encoded_secret_redaction_gap" and r["passed"] is False for r in summary["results"])
            assert any(r["case_key"] == "system_prompt_disclosure_not_applicable" and r["applicable"] is False for r in summary["results"])

            listing = await client.get("/api/v2/red-team/runs", headers=headers)
            assert listing.status_code == 200
            assert listing.json()["total"] >= 1

            detail = await client.get(f"/api/v2/red-team/runs/{summary['run_id']}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["run_id"] == summary["run_id"]
        finally:
            await client.delete(f"/api/v2/features/red_team_lab/overrides/{override_id}", headers=headers)
            async with async_session_maker() as db:
                await db.execute(text("DELETE FROM red_team_runs WHERE tenant_id=:t"), {"t": tenant_id})
                await db.commit()
