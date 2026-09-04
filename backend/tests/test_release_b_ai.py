from datetime import datetime, timezone

from ai.agents.grounding import validate_grounding
from ai.agents.technical_entities import extract_technical_entities
from ai.graph import PipelineStageError, _instrument
from ai.graph.nodes import attachment_or_text_node, confidence_node
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


def test_technical_entity_extraction_preserves_vpn_error_and_windows():
    text = "Windows 11 laptop shows VPN-809 when connecting to https://vpn.example.com from 10.2.3.4."
    entities = extract_technical_entities(text)
    values = {(item["entity_type"], item["raw_value"]) for item in entities}
    assert ("error_code", "VPN-809") in values
    assert ("operating_system", "Windows 11") in values
    assert ("url", "https://vpn.example.com") in values
    assert ("ipv4", "10.2.3.4") in values


def test_ordinary_number_is_not_mistaken_for_error_code():
    entities = extract_technical_entities("The issue happened 17 times at 10:30.")
    assert not [item for item in entities if item["entity_type"] == "error_code"]


def test_extended_entities_keep_structured_values_and_attempted_step():
    text = "On 2026-09-04 at 14:30, host vpn-gw-01.example.test failed in Cisco AnyConnect. I restarted the laptop after a suspicious login."
    values={(item["entity_type"],item["raw_value"]) for item in extract_technical_entities(text)}
    assert ("date","2026-09-04") in values
    assert ("time","14:30") in values
    assert ("host_name","vpn-gw-01.example.test") in values
    assert ("application_name","Cisco AnyConnect") in values
    assert ("security_indicator","suspicious login") in values
    assert any(kind=="troubleshooting_attempt" and "restarted" in value for kind,value in values)


@pytest.mark.asyncio
async def test_attachment_path_and_confidence_fallback_are_explicit(monkeypatch):
    attached=await attachment_or_text_node({"processed_text":"Customer text","attachment_text":"OCR evidence"})
    assert attached["processed_text"]=="Customer text\nOCR evidence"
    monkeypatch.setattr("ai.graph.nodes.predict_confidence",lambda features:(.42,"safe-fallback-test",False))
    result=await confidence_node({"description":"VPN fails","retrieved_chunks":[],"citation_validation":{"citation_coverage":0},"grounding_validation":{"overall_status":"Unsupported"},"low_confidence_threshold":.55,"high_confidence_threshold":.8})
    assert result["confidence_band"]=="low"
    assert result["fallback_used"] is True
    assert result["confidence_provider"]=="deterministic_fallback"


@pytest.mark.asyncio
async def test_instrumented_failure_retains_completed_safe_trace():
    async def succeeds(_state): return {"routing_status":"routed"}
    async def fails(_state): raise TimeoutError("sensitive provider details")
    first=await _instrument("route",succeeds,6)({})
    with pytest.raises(PipelineStageError) as raised:
        await _instrument("retrieve",fails,7)(first)
    assert raised.value.sequence_number==7
    assert raised.value.error_category=="TimeoutError"
    assert [row["stage_name"] for row in raised.value.completed_trace]==["route"]


def test_grounding_validator_supports_matching_citation_and_blocks_unsafe_claim():
    evidence = [{"citation_id":"KB-001","chunk_text":"Reset cached VPN credentials and reconnect to the VPN client."}]
    supported = validate_grounding("Reset cached VPN credentials and reconnect. [KB-001]", evidence, {"valid":True})
    assert supported["overall_status"] == "Grounded"
    assert supported["claims"][0]["validation_status"] == "Supported"

    unsafe = validate_grounding("Disable the firewall and share your password. [KB-001]", evidence, {"valid":True})
    assert unsafe["overall_status"] == "Human Investigation Required"
    assert unsafe["blocked"] is True


def test_grounding_validator_rejects_fabricated_citation():
    result = validate_grounding("Run the repair command. [KB-999]", [], {"valid":False})
    assert result["overall_status"] == "Unsupported"
    assert result["claims"][0]["validation_status"] == "Unsupported"


def test_grounding_validator_flags_conflicting_approved_sources():
    evidence=[{"citation_id":"KB-001","chunk_text":"Administrators must enable secure remote access for the VPN service."},{"citation_id":"KB-002","chunk_text":"Administrators must disable secure remote access for the VPN service."}]
    result=validate_grounding("Follow the approved VPN configuration. [KB-001]",evidence,{"valid":True})
    assert result["overall_status"]=="Conflicting Evidence"
    assert result["blocked"] is True
    assert result["contradictions"]


def test_grounding_validator_marks_direct_opposite_claim_contradicted():
    evidence=[{"citation_id":"KB-001","chunk_text":"Administrators must disable legacy remote access."}]
    result=validate_grounding("Administrators must enable legacy remote access. [KB-001]",evidence,{"valid":True})
    assert result["claims"][0]["validation_status"]=="Contradicted"
    assert result["overall_status"]=="Conflicting Evidence"


@pytest.mark.asyncio(loop_scope="session")
async def test_release_b_trace_entities_explanation_and_customer_denial():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def login(email):
            response=await client.post("/api/auth/login",data={"username":email,"password":"Demo@123"})
            assert response.status_code==200,response.text
            return {"Authorization":f"Bearer {response.json()['access_token']}"}
        customer=await login("customer@demo.com");lead=await login("teamlead@demo.com");agent=await login("agent@demo.com");reviewer=await login("reviewer@demo.com");auditor=await login("auditor@demo.com");knowledge=await login("kbmanager@demo.com")
        created=await client.post("/api/tickets",headers=customer,json={"subject":"VPN-809 on Windows 11","description":"Unable to connect to the company VPN on Windows 11. Error code VPN-809 appears after entering credentials. Restarting the laptop did not solve the issue."})
        assert created.status_code==201,created.text;ticket_id=created.json()["id"]
        generated=await client.post(f"/api/tickets/{ticket_id}/ai-draft/generate",headers=lead,json={"article_version":"1.0"})
        assert generated.status_code==200,generated.text
        assert generated.json()["draft_text"],generated.text
        trace=await client.get(f"/api/tickets/{ticket_id}/pipeline-trace",headers=lead)
        assert trace.status_code==200,trace.text
        names=[stage["stage_name"] for stage in trace.json()["stages"]]
        assert names==["intake","attachment_or_text","technical_entity","classify","priority","route","retrieve","draft","validate_citations","validate_grounding","confidence","human_review_gate"]
        assert all(stage["duration_ms"]>=0 for stage in trace.json()["stages"])
        entities=await client.get(f"/api/tickets/{ticket_id}/technical-entities",headers=lead)
        assert entities.status_code==200
        assert {item["raw_value"] for item in entities.json()}>={"VPN-809","Windows 11"}
        why=await client.get(f"/api/tickets/{ticket_id}/explanation",headers=lead)
        assert why.status_code==200
        assert why.json()["confidence_score"] is not None
        assert (await client.get(f"/api/tickets/{ticket_id}/pipeline-trace",headers=auditor)).status_code==200
        assert (await client.post(f"/api/tickets/{ticket_id}/technical-entities/{entities.json()[0]['id']}/corrections",headers=auditor,json={"normalized_value":"forbidden","reason":"Auditors are read only"})).status_code==403
        assert (await client.get(f"/api/tickets/{ticket_id}/pipeline-trace",headers=knowledge)).status_code==403
        for suffix in ("pipeline-trace","technical-entities","explanation"):
            denied=await client.get(f"/api/tickets/{ticket_id}/{suffix}",headers=customer)
            assert denied.status_code==403

        profile=(await client.get("/api/auth/me",headers=agent)).json()
        assigned=await client.post(f"/api/tickets/{ticket_id}/assign",headers=lead,json={"engineer_id":profile["id"],"comment":"VPN specialization and controlled workload"})
        assert assigned.status_code==200,assigned.text
        started=await client.post(f"/api/tickets/{ticket_id}/start-work",headers=agent,json={"comment":"Investigating evidence"})
        assert started.status_code==200,started.text
        version=await client.post(f"/api/tickets/{ticket_id}/drafts",headers=agent,json={"content":generated.json()["draft_text"],"citations":generated.json()["citations"]})
        assert version.status_code==201,version.text
        assert version.json()["citation_validation_status"]=="valid"
        submitted=await client.post(f"/api/tickets/{ticket_id}/submit-for-review",headers=agent,json={"comment":"Evidence checked"})
        assert submitted.status_code==200,submitted.text
        approved=await client.post(f"/api/tickets/{ticket_id}/review",headers=reviewer,json={"action":"approve","review_comment":"Citations and grounding verified"})
        assert approved.status_code==200,approved.text
        customer_view=await client.get(f"/api/tickets/{ticket_id}",headers=customer)
        assert customer_view.json()["final_response"]==generated.json()["draft_text"]


@pytest.mark.asyncio(loop_scope="session")
async def test_failed_pipeline_execution_is_persisted(monkeypatch):
    import ai.graph as graph_module

    class BrokenGraph:
        async def ainvoke(self,_state):
            now=datetime.now(timezone.utc).isoformat()
            completed=[{"stage_name":"intake","sequence_number":1,"status":"completed","input_summary":"safe","output_summary":"processed","provider_name":"deterministic","provider_version":"release-b-1.0","confidence":None,"started_at":now,"completed_at":now,"duration_ms":0,"fallback_used":False,"metadata":{}}]
            raise PipelineStageError("attachment_or_text",2,TimeoutError("private upstream text"),now,1,completed)

    monkeypatch.setattr(graph_module,"graph",BrokenGraph())
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        async def login(email):
            response=await client.post("/api/auth/login",data={"username":email,"password":"Demo@123"})
            return {"Authorization":f"Bearer {response.json()['access_token']}"}
        customer=await login("customer@demo.com");lead=await login("teamlead@demo.com")
        created=await client.post("/api/tickets",headers=customer,json={"subject":"VPN pipeline failure test","description":"VPN-809 on Windows 11 must remain safely submitted."})
        ticket_id=created.json()["id"]
        generated=await client.post(f"/api/tickets/{ticket_id}/ai-draft/generate",headers=lead,json={"article_version":"1.0"})
        assert generated.status_code==200
        assert generated.json()["generation_status"]=="failed"
        trace=(await client.get(f"/api/tickets/{ticket_id}/pipeline-trace",headers=lead)).json()
        assert trace["execution"]["status"]=="failed"
        assert trace["execution"]["failure_stage"]=="attachment_or_text"
        assert [(row["stage_name"],row["status"]) for row in trace["stages"]]==[("intake","completed"),("attachment_or_text","failed")]
        assert "private upstream text" not in str(trace)
