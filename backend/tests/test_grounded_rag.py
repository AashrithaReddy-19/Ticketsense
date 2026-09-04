import asyncio
import pytest
from ai.agents.llm_interface import DeterministicDevelopmentProvider
from ai.graph.nodes import validate_citations_node
from ai.graph import nodes

def evidence(**overrides):
    row={"citation_id":"KB-001","article_id":"article-1","tenant_id":"tenant-1","department_id":"dept-1","department":"Networking","title":"VPN","chunk_text":"Reset stored VPN credentials.","distance":.4,"similarity":.6,"article_version":"1.0","status":"approved","is_publishable":True}
    row.update(overrides); return row

def test_deterministic_provider_is_grounded_and_handles_empty_evidence():
    provider=DeterministicDevelopmentProvider(); result=asyncio.run(provider.generate_grounded_draft({},[evidence()]))
    assert result.provider=="deterministic-development" and "[KB-001]" in result.content.draft_text
    assert {c.citation_id for c in result.content.citations}=={"KB-001"}
    empty=asyncio.run(provider.generate_grounded_draft({},[]))
    assert empty.content.insufficient_evidence and not empty.content.citations
    assert "does not contain enough information" in empty.content.draft_text

def test_valid_citation_passes_and_unknown_fails():
    base={"tenant_id":"tenant-1","department_id":"dept-1","article_version":"1.0","retrieved_chunks":[evidence()],"generation_status":"generated","insufficient_evidence":False}
    valid=asyncio.run(validate_citations_node({**base,"draft_reply":"Use the documented procedure [KB-001].","citations":[{"citation_id":"KB-001"}]}))
    assert valid["citation_validation"]["valid"]
    invalid=asyncio.run(validate_citations_node({**base,"draft_reply":"Unsupported [KB-999].","citations":[{"citation_id":"KB-999"}]}))
    assert not invalid["citation_validation"]["valid"] and "KB-999" in invalid["citation_validation"]["invalid_citation_ids"]

@pytest.mark.parametrize("change",[
    {"tenant_id":"tenant-2"},{"department_id":"dept-2"},{"article_version":"2.0"},
    {"status":"draft"},{"is_publishable":False},{"chunk_text":""},
])
def test_cross_scope_or_unpublishable_evidence_is_rejected(change):
    state={"tenant_id":"tenant-1","department_id":"dept-1","article_version":"1.0","retrieved_chunks":[evidence(**change)],"draft_reply":"Guidance [KB-001].","citations":[{"citation_id":"KB-001"}],"generation_status":"generated"}
    result=asyncio.run(validate_citations_node(state))
    assert not result["citation_validation"]["valid"]

def test_insufficient_evidence_response_needs_no_citation():
    result=asyncio.run(validate_citations_node({"tenant_id":"t","department_id":"d","article_version":"1.0","retrieved_chunks":[],"draft_reply":"The available knowledge base does not contain enough information.","citations":[],"insufficient_evidence":True,"generation_status":"generated"}))
    assert result["citation_validation"]["valid"]

def test_graph_order():
    from ai.graph import graph
    edges={(edge.source,edge.target) for edge in graph.get_graph().edges}
    ordered = ["__start__", "intake", "attachment_or_text", "technical_entity", "classify", "priority", "route", "retrieve", "draft", "validate_citations", "validate_grounding", "confidence", "human_review_gate", "__end__"]
    assert {(before, after) for before, after in zip(ordered, ordered[1:])} == edges

def test_provider_timeout_is_controlled(monkeypatch):
    class Slow:
        async def generate_grounded_draft(self,*args,**kwargs):
            await asyncio.sleep(.05)
    monkeypatch.setattr(nodes,"get_llm_provider",lambda _:Slow()); monkeypatch.setattr(nodes,"_LLM_TIMEOUT_SECONDS",.001)
    result=asyncio.run(nodes.draft_node({"subject":"x","description":"y","retrieved_chunks":[]}))
    assert result["generation_status"]=="failed" and result["generation_error"]=="TimeoutError"

def test_malformed_provider_output_is_controlled(monkeypatch):
    class Malformed:
        async def generate_grounded_draft(self,*args,**kwargs): return {"unstructured":"text"}
    monkeypatch.setattr(nodes,"get_llm_provider",lambda _:Malformed())
    result=asyncio.run(nodes.draft_node({"subject":"x","description":"y","retrieved_chunks":[]}))
    assert result["generation_status"]=="failed" and result["generation_error"]=="AttributeError"
