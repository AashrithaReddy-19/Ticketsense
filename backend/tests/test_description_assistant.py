import pytest

from ai.agents.llm_interface import DeterministicDevelopmentProvider


@pytest.mark.asyncio
async def test_description_assistant_preserves_supplied_facts_and_asks_for_gaps():
    result = await DeterministicDevelopmentProvider().improve_description(
        "vpn error", "vpn not connect from morning tried restart"
    )
    assert "VPN" in result.suggested
    assert "this morning" in result.suggested
    assert "restarting" in result.suggested
    assert "error message" in " ".join(result.missing_information_questions).lower()
    assert result.provider == "deterministic-development"


@pytest.mark.asyncio
async def test_description_assistant_does_not_invent_missing_error_or_device():
    original = "Payroll page is not working"
    result = await DeterministicDevelopmentProvider().improve_description(
        "Payroll unavailable", original
    )
    assert "error code" not in result.suggested.lower()
    assert "windows" not in result.suggested.lower()
    assert "mac" not in result.suggested.lower()
    assert any("error message" in question.lower() for question in result.missing_information_questions)

