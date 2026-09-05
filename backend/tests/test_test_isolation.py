"""Regression check for the test-pollution fix in conftest.py: a ticket registered
with the ``demo_tickets`` fixture must actually be gone once that test finishes,
never accumulating in the (real, seeded) demo tenant across repeated test runs.

Uses two ordered tests rather than asserting inside a single test, because the
thing under test is fixture *teardown* behavior, which only runs after the test
function using it has already returned control."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import async_session_maker
from app.models.ticket import Ticket
from app.models.user import User

_MARKER_SUBJECT = f"test-isolation-regression-check-{uuid4().hex}"
_holder: dict[str, str] = {}


@pytest.mark.asyncio(loop_scope="session")
async def test_a_ticket_registered_with_the_fixture_exists_during_the_test(demo_tickets):
    async with async_session_maker() as db:
        customer = await db.scalar(select(User).where(User.email == "customer@demo.com"))
        assert customer is not None, "the seeded demo customer must exist for this check to be meaningful"
        ticket = Ticket(tenant_id=customer.tenant_id, submitted_by=customer.id, subject=_MARKER_SUBJECT,
                         description="Direct-DB ticket created only to prove fixture teardown cleans it up.",
                         status="submitted", priority="medium", sentiment="neutral")
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)
        _holder["id"] = str(ticket.id)

    demo_tickets.append(_holder["id"])

    async with async_session_maker() as db:
        assert await db.get(Ticket, _holder["id"]) is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_the_previous_tests_ticket_was_deleted_by_fixture_teardown():
    assert "id" in _holder, "the previous test must run first and register a ticket"
    async with async_session_maker() as db:
        assert await db.get(Ticket, _holder["id"]) is None, (
            "the demo_tickets fixture did not clean up its ticket -- this is exactly "
            "the regression (test-suite pollution of the shared demo tenant) it exists to prevent"
        )
