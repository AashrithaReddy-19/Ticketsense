"""Verifies the Phase 14 configurable real LLM provider: it fails closed with no
key, parses a well-formed structured response into a grounded draft, degrades to a
controlled failure (never an unhandled exception) on malformed output or a
persistent server error, retries transient errors before giving up, and never
retries a non-429 4xx. No real network call is made anywhere in this file."""
import json

import httpx
import pytest

from ai.agents.llm_interface import DeterministicDevelopmentProvider, OpenAICompatibleProvider, get_llm_provider

EVIDENCE = [{"citation_id": "KB-001", "article_id": "a1", "title": "VPN reset", "article_version": "1.0", "chunk_text": "Reset the cached VPN credentials."}]
_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before any test monkeypatches httpx.AsyncClient


def _client_factory(handler):
    def factory(*args, **kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))
    return factory


def _chat_response(content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json={"choices": [{"message": {"content": content}}]} if status_code < 400 else {"error": "boom"})


def test_get_llm_provider_fails_closed_with_no_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        get_llm_provider("openai_compatible")


def test_get_llm_provider_still_defaults_to_the_deterministic_provider():
    assert isinstance(get_llm_provider("stub"), DeterministicDevelopmentProvider)


@pytest.mark.asyncio
async def test_well_formed_response_is_parsed_into_a_grounded_draft(monkeypatch):
    payload = json.dumps({"draft_text": "Reset your cached VPN credentials [KB-001].", "citations": [{"citation_id": "KB-001"}], "insufficient_evidence": False})
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(lambda req: _chat_response(payload)))
    provider = OpenAICompatibleProvider(api_key="k", base_url="https://api.example.test/v1", model="test-model", timeout_seconds=5, max_retries=0)
    result = await provider.generate_grounded_draft({"subject": "VPN", "description": "broken"}, EVIDENCE)
    assert result.error is None and result.provider == "openai_compatible" and result.model == "test-model"
    assert result.content.draft_text == "Reset your cached VPN credentials [KB-001]."
    assert result.content.citations[0].citation_id == "KB-001" and result.content.citations[0].article_id == "a1"


@pytest.mark.asyncio
async def test_malformed_json_output_becomes_a_controlled_failure_not_an_exception(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(lambda req: _chat_response("not json at all")))
    provider = OpenAICompatibleProvider(api_key="k", base_url="https://api.example.test/v1", model="test-model", timeout_seconds=5, max_retries=0)
    result = await provider.generate_grounded_draft({"subject": "x", "description": "y"}, [])
    assert result.error is not None and result.content is None


@pytest.mark.asyncio
async def test_a_persistent_server_error_becomes_a_controlled_failure_after_retries(monkeypatch):
    calls = {"count": 0}
    def handler(req):
        calls["count"] += 1
        return httpx.Response(503, json={"error": "unavailable"})
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    provider = OpenAICompatibleProvider(api_key="k", base_url="https://api.example.test/v1", model="test-model", timeout_seconds=5, max_retries=2)
    monkeypatch.setattr("asyncio.sleep", lambda *_: _no_sleep())
    result = await provider.generate_grounded_draft({"subject": "x", "description": "y"}, [])
    assert result.error is not None
    assert calls["count"] == 3  # initial attempt + 2 retries


@pytest.mark.asyncio
async def test_a_client_error_is_not_retried(monkeypatch):
    calls = {"count": 0}
    def handler(req):
        calls["count"] += 1
        return httpx.Response(400, json={"error": "bad request"})
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    provider = OpenAICompatibleProvider(api_key="k", base_url="https://api.example.test/v1", model="test-model", timeout_seconds=5, max_retries=3)
    result = await provider.generate_grounded_draft({"subject": "x", "description": "y"}, [])
    assert result.error is not None
    assert calls["count"] == 1


async def _no_sleep():
    return None
