import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def login(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/auth/login",
        data={"username": email, "password": "Demo@123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_ticket_is_synchronized_across_customer_engineer_and_reviewer(demo_tickets):
    """One shared ticket progresses atomically and exposes only approved content."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        customer = await login(client, "customer@demo.com")
        engineer = await login(client, "agent@demo.com")
        reviewer = await login(client, "reviewer@demo.com")
        team_lead = await login(client, "teamlead@demo.com")
        engineer_profile = await client.get("/api/auth/me", headers=auth(engineer))
        assert engineer_profile.status_code == 200

        created = await client.post(
            "/api/tickets",
            headers=auth(customer),
            json={
                "subject": "VPN test workflow synchronization",
                "description": "The corporate VPN rejects my valid password from home.",
            },
        )
        assert created.status_code == 201, created.text
        ticket_id = created.json()["id"]
        demo_tickets.append(ticket_id)
        assert created.json()["status"] in {"routed", "assigned"}
        assert created.json()["ai_draft_reply"] is None
        assert created.json()["final_response"] is None

        assigned = await client.post(
            f"/api/tickets/{ticket_id}/assign",
            headers=auth(team_lead),
            json={"engineer_id": engineer_profile.json()["id"], "comment": "Deterministic workflow-test assignment."},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["status"] == "assigned"

        started = await client.post(
            f"/api/tickets/{ticket_id}/start-work",
            headers=auth(engineer),
            json={"comment": "Investigating VPN authentication."},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "in_progress"

        first = await client.post(
            f"/api/tickets/{ticket_id}/drafts",
            headers=auth(engineer),
            json={"content": "Reset the cached VPN credentials and reconnect."},
        )
        assert first.status_code == 201, first.text
        second = await client.post(
            f"/api/tickets/{ticket_id}/drafts",
            headers=auth(engineer),
            json={
                "content": "Remove the cached VPN credentials, sign in again, and reconnect.",
                "based_on_draft_id": first.json()["id"],
            },
        )
        assert second.status_code == 201, second.text
        assert second.json()["version_number"] == first.json()["version_number"] + 1

        drafts = await client.get(
            f"/api/tickets/{ticket_id}/drafts", headers=auth(engineer)
        )
        assert drafts.status_code == 200
        assert [item["status"] for item in reversed(drafts.json())] == [
            "superseded",
            "engineer_edited",
        ]

        comparison = await client.get(
            f"/api/tickets/{ticket_id}/draft-comparison", headers=auth(engineer)
        )
        assert comparison.status_code == 200, comparison.text
        assert comparison.json()["from_version"] == first.json()["version_number"]
        assert comparison.json()["to_version"] == second.json()["version_number"]
        assert comparison.json()["edit_percentage"] > 0
        assert comparison.json()["added_word_count"] > 0

        hidden_comparison = await client.get(
            f"/api/tickets/{ticket_id}/draft-comparison", headers=auth(customer)
        )
        assert hidden_comparison.status_code == 403

        submitted = await client.post(
            f"/api/tickets/{ticket_id}/submit-for-review",
            headers=auth(engineer),
            json={"comment": "Resolution tested and ready for review."},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "pending_review"

        invalid_repeat = await client.post(
            f"/api/tickets/{ticket_id}/submit-for-review",
            headers=auth(engineer),
            json={"comment": "This transition must not be accepted twice."},
        )
        assert invalid_repeat.status_code == 409

        before_approval = await client.get(
            f"/api/tickets/{ticket_id}", headers=auth(customer)
        )
        assert before_approval.status_code == 200
        assert before_approval.json()["status"] == "pending_review"
        assert before_approval.json()["ai_draft_reply"] is None
        assert before_approval.json()["final_response"] is None

        approved = await client.post(
            f"/api/tickets/{ticket_id}/review",
            headers=auth(reviewer),
            json={
                "action": "approve",
                "review_comment": "Evidence and troubleshooting steps verified.",
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "resolved"

        customer_view = await client.get(
            f"/api/tickets/{ticket_id}", headers=auth(customer)
        )
        assert customer_view.status_code == 200
        assert customer_view.json()["status"] == "resolved"
        assert customer_view.json()["ai_draft_reply"] is None
        assert customer_view.json()["final_response"] == second.json()["content"]
        assert customer_view.json()["final_responder_name"]
        assert customer_view.json()["approved_at"]
        assert customer_view.json()["resolved_at"]

        timeline = await client.get(
            f"/api/tickets/{ticket_id}/timeline", headers=auth(customer)
        )
        assert timeline.status_code == 200
        event_types = [event["event_type"] for event in timeline.json()]
        assert "ticket_submitted" in event_types
        assert {"assignment_accepted", "ticket_assigned"} & set(event_types)
        assert "ticket_resolved" in event_types
        assert all(event["actor_role"] is None for event in timeline.json())
