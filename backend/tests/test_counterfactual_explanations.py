"""Unit tests for the deterministic counterfactual-explanation generator
(app.services.counterfactual), plus API-level coverage for the endpoint that
gets-or-creates and serves role-appropriate views of it.
"""
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.database import async_session_maker
from app.main import app
from app.models.counterfactual import CounterfactualExplanation
from app.models.enterprise import TicketDecision
from app.models.user import User
from app.services.counterfactual import build_explanation
from app.services.resolution_policy import process_resolution_decision
from test_resolution_policy_and_assignment import make_grounded_draft, make_permissive_policy, make_ticket, scenario


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def headers_for(user_id: UUID, role: str, department_id, tenant_id) -> dict[str, str]:
    return auth(create_access_token(user_id, role, department_id, tenant_id))


ALL_OTHER_PASSED_GATES = [
    "policy_enabled", "category_allowlisted", "category_not_sensitive", "not_critical",
    "overall_confidence", "classification_confidence", "classification_margin",
    "approved_current_evidence", "retrieval_relevance", "citation_validation",
    "claim_grounding", "no_contradiction", "pii_secrets", "attachment_quality",
    "pipeline_complete", "immutable_response_available", "playbook_compatible", "no_immediate_repeat",
    "no_unresolved_knowledge_conflict",
]


def test_evidence_gap_matches_spec_example_wording():
    result = build_explanation(
        passed_gates=ALL_OTHER_PASSED_GATES, failed_gates=["citation_coverage"],
        factors={"citation_coverage": {"score": 0.64, "threshold": 0.80, "detail": None}},
    )
    assert "64%" in result["narrative_internal"]
    assert "80%" in result["narrative_internal"]
    assert result["immutable_reasons"] == []
    assert len(result["evidence_gaps"]) == 1
    assert result["evidence_gaps"][0]["code"] == "citation_coverage"


def test_sensitive_category_produces_regardless_of_confidence_wording():
    result = build_explanation(
        passed_gates=[], failed_gates=["category_not_sensitive"],
        factors={"category_not_sensitive": {"score": None, "threshold": None, "detail": "Sensitive categories always require a human"}},
    )
    assert result["narrative_internal"].startswith("This ticket requires human review regardless of confidence")
    assert len(result["immutable_reasons"]) == 1
    assert result["evidence_gaps"] == []


def test_minimal_safe_change_matches_spec_example_wording():
    result = build_explanation(
        passed_gates=[], failed_gates=["retrieval_relevance"],
        factors={"retrieval_relevance": {"score": 0.5, "threshold": 0.75, "detail": None}},
    )
    change = result["evidence_gaps"][0]["minimal_safe_change"]
    assert change is not None
    assert "0.75" in change
    assert "approved source" in change


def test_two_independent_blocking_reasons_state_still_blocked():
    result = build_explanation(
        passed_gates=[], failed_gates=["category_not_sensitive", "no_contradiction"],
        factors={
            "category_not_sensitive": {"score": None, "threshold": None, "detail": "Sensitive categories always require a human"},
            "no_contradiction": {"score": None, "threshold": None, "detail": "Contradiction validator"},
        },
    )
    assert len(result["immutable_reasons"]) == 1
    assert len(result["evidence_gaps"]) == 1
    assert "still be blocked" in result["narrative_internal"]


def test_customer_wording_never_leaks_gate_codes_or_thresholds():
    result = build_explanation(
        passed_gates=[], failed_gates=["citation_coverage", "category_not_sensitive"],
        factors={
            "citation_coverage": {"score": 0.64, "threshold": 0.80, "detail": None},
            "category_not_sensitive": {"score": None, "threshold": None, "detail": None},
        },
    )
    customer_text = result["narrative_customer"].lower()
    assert "citation_coverage" not in customer_text
    assert "0.64" not in customer_text
    assert "80%" not in customer_text
    assert "gate" not in customer_text


def test_all_gates_passed_produces_no_review_required_narrative():
    result = build_explanation(passed_gates=ALL_OTHER_PASSED_GATES + ["citation_coverage"], failed_gates=[], factors={})
    assert result["immutable_reasons"] == []
    assert result["evidence_gaps"] == []
    assert "no human review was required" in result["narrative_internal"]


@pytest.mark.asyncio(loop_scope="session")
async def test_counterfactual_endpoint_is_feature_flag_gated_and_cached(scenario):
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        await make_grounded_draft(db, ticket)
        await db.commit()
        decision = await process_resolution_decision(db, ticket)
        await db.commit()
        assert decision.decision != "auto_resolve"
        assert "policy_enabled" in decision.failed_gates

        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-cf-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.commit()
        engineer_headers = headers_for(scenario["engineer_id"], "support_agent", scenario["department_id"], scenario["tenant_id"])
        customer_headers = headers_for(scenario["customer_id"], "customer", None, scenario["tenant_id"])
        admin_headers = headers_for(admin_id, "system_admin", None, scenario["tenant_id"])
        ticket_id = str(ticket.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        gated = await client.get(f"/api/v2/tickets/{ticket_id}/counterfactual", headers=engineer_headers)
        assert gated.status_code == 404  # counterfactual_explanations flag disabled by default

        override = await client.post(
            "/api/v2/features/counterfactual_explanations/overrides", headers=admin_headers, json={
                "scope_type": "tenant", "scope_value": str(scenario["tenant_id"]), "enabled": True,
                "rollout_percentage": 100, "reason": "Counterfactual explanation test",
            },
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]

        try:
            internal = await client.get(f"/api/v2/tickets/{ticket_id}/counterfactual", headers=engineer_headers)
            assert internal.status_code == 200, internal.text
            body = internal.json()
            assert "policy_enabled" in [g["code"] for g in body["blocking_gates"]]
            assert body["immutable_reasons"]

            customer = await client.get(f"/api/v2/tickets/{ticket_id}/counterfactual", headers=customer_headers)
            assert customer.status_code == 200
            customer_body = customer.json()
            assert set(customer_body) == {"ticket_id", "decision_outcome", "requires_human_review", "narrative", "created_at"}
            assert customer_body["requires_human_review"] is True
            assert "policy_enabled" not in customer_body["narrative"]

            # Second call must return the same cached row, not a new one.
            async with async_session_maker() as db:
                rows = (await db.scalars(select(CounterfactualExplanation).where(CounterfactualExplanation.ticket_id == UUID(ticket_id)))).all()
                assert len(rows) == 1
        finally:
            await client.delete(f"/api/v2/features/counterfactual_explanations/overrides/{override_id}", headers=admin_headers)
