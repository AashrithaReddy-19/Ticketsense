import asyncio, os, re
from pathlib import Path
import asyncpg
from dotenv import dotenv_values
from pgvector.asyncpg import register_vector
from ai.agents.llm_interface import get_llm_provider
from .state import TicketState
from ai.agents.technical_entities import extract_technical_entities
from ai.agents.grounding import validate_grounding
from ai.models.confidence_model import predict_confidence

ROOT=Path(__file__).resolve().parents[2]; ARTIFACTS_DIR=Path(__file__).resolve().parents[1]/"models"/"artifacts"; _env=dotenv_values(ROOT/".env")
_MODEL_NAME=os.environ.get("EMBEDDING_MODEL") or _env.get("EMBEDDING_MODEL","sentence-transformers/all-MiniLM-L6-v2")
_DATABASE_URL=os.environ.get("DATABASE_URL") or _env.get("DATABASE_URL",""); _LLM_PROVIDER=os.environ.get("LLM_PROVIDER") or _env.get("LLM_PROVIDER","stub")
_LLM_TIMEOUT_SECONDS=float(os.environ.get("LLM_TIMEOUT_SECONDS") or _env.get("LLM_TIMEOUT_SECONDS","30"))
_MODEL_LOAD_TIMEOUT_SECONDS=float(os.environ.get("MODEL_LOAD_TIMEOUT_SECONDS") or _env.get("MODEL_LOAD_TIMEOUT_SECONDS","120"))
_embedding_model=None; _classifiers=None

async def intake_node(state:TicketState)->dict:
    return {"processed_text":f"{state.get('subject','')}\n{state.get('description','')}".strip()}

async def attachment_or_text_node(state:TicketState)->dict:
    attachment=(state.get("attachment_text") or "").strip()
    base=(state.get("processed_text") or state.get("description") or "").strip()
    return {"processed_text":f"{base}\n{attachment}".strip() if attachment else base}

async def technical_entity_node(state:TicketState)->dict:
    return {"technical_entities":extract_technical_entities(state.get("processed_text",state.get("description","")),"attachment_and_description" if state.get("attachment_text") else "description")}

async def priority_node(state:TicketState)->dict:
    return {"priority":state.get("priority","medium")}

def _asyncpg_url(url): return re.sub(r"^postgresql\+asyncpg://","postgresql://",url)
def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model=SentenceTransformer(_MODEL_NAME)
    return _embedding_model
def _get_classifiers():
    global _classifiers
    if _classifiers is None:
        import joblib
        _classifiers={}
        for target in ("department","priority","sentiment"):
            path=ARTIFACTS_DIR/f"{target}_classifier.joblib"
            if not path.exists(): raise FileNotFoundError(f"{path} not found; run ai/models/train_classifier.py")
            _classifiers[target]=joblib.load(path)
    return _classifiers

async def classify_node(state:TicketState)->dict:
    text=f"{state['subject']}\n{state['description']}\n{state.get('attachment_text','')}"
    def _predict():
        models=_get_classifiers()
        return {key:str(models[key].predict([text])[0]) for key in ("department","priority","sentiment")}
    return await asyncio.wait_for(asyncio.to_thread(_predict),timeout=_MODEL_LOAD_TIMEOUT_SECONDS)

async def route_node(state:TicketState)->dict:
    if not state.get("tenant_id") or not state.get("department"): raise ValueError("route_node requires tenant_id and department")
    conn=await asyncpg.connect(_asyncpg_url(_DATABASE_URL))
    try:
        if state.get("department_id"):
            row=await conn.fetchrow("SELECT id,name FROM departments WHERE tenant_id=$1::uuid AND id=$2::uuid",state["tenant_id"],state["department_id"])
        else:
            row=await conn.fetchrow("SELECT id,name FROM departments WHERE tenant_id=$1::uuid AND name=$2",state["tenant_id"],state["department"])
    finally: await conn.close()
    return {"department_id":str(row["id"]) if row else "","department":row["name"] if row else state["department"],"routing_status":"routed" if row else "manual_triage"}

async def retrieve_node(state:TicketState,top_k:int=3)->dict:
    """Retrieves from two tenant/department-scoped, publishable-only evidence sources:
    curated knowledge-base articles and approved historical ticket resolutions. Both
    queries apply the identical tenant_id/department_id filter before ranking, so
    neither source can leak another tenant's or department's data."""
    if not state.get("tenant_id") or not state.get("department_id"): raise ValueError("retrieve_node requires tenant_id and department_id")
    query=f"Subject: {state['subject']}\nDescription: {state['description']}"
    if state.get("attachment_text"):query+=f"\n<UNTRUSTED_ATTACHMENT_DATA>\n{state['attachment_text']}\n</UNTRUSTED_ATTACHMENT_DATA>"
    vector=await asyncio.wait_for(asyncio.to_thread(lambda:_get_embedding_model().encode(query).tolist()),timeout=_MODEL_LOAD_TIMEOUT_SECONDS); version=state.get("article_version","1.0")
    conn=await asyncpg.connect(_asyncpg_url(_DATABASE_URL)); await register_vector(conn)
    try:
        kb_rows=await conn.fetch("""SELECT k.id article_id,k.tenant_id,k.department_id,d.name department,k.title,k.version article_version,k.status,k.is_publishable,e.chunk_text,e.embedding <=> $1 distance,1-(e.embedding <=> $1) similarity FROM embeddings e JOIN knowledge_base k ON k.id=e.knowledge_base_id JOIN departments d ON d.id=k.department_id WHERE k.tenant_id=$2::uuid AND k.department_id=$3::uuid AND k.status='approved' AND k.version=$4 AND k.is_publishable=true AND length(trim(k.content))>0 AND length(trim(e.chunk_text))>0 ORDER BY e.embedding <=> $1 LIMIT $5""",vector,state["tenant_id"],state["department_id"],version,top_k)
        resolution_rows=await conn.fetch("""SELECT r.ticket_id article_id,r.tenant_id,r.department_id,d.name department,r.source_version article_version,r.chunk_text,r.embedding <=> $1 distance,1-(r.embedding <=> $1) similarity FROM ticket_resolution_embeddings r JOIN departments d ON d.id=r.department_id WHERE r.tenant_id=$2::uuid AND r.department_id=$3::uuid AND r.reusable=true AND r.ticket_id!=COALESCE(NULLIF($4,'')::uuid,'00000000-0000-0000-0000-000000000000'::uuid) AND length(trim(r.chunk_text))>0 ORDER BY r.embedding <=> $1 LIMIT $5""",vector,state["tenant_id"],state["department_id"],state.get("ticket_id",""),top_k)
    finally: await conn.close()
    kb_chunks=[{"citation_id":"","article_id":str(r["article_id"]),"source_id":str(r["article_id"]),"source_type":"knowledge_base","tenant_id":str(r["tenant_id"]),"department_id":str(r["department_id"]),"department":r["department"],"title":r["title"],"chunk_text":r["chunk_text"],"distance":float(r["distance"]),"similarity":float(r["similarity"]),"article_version":r["article_version"],"status":r["status"],"is_publishable":r["is_publishable"]} for r in kb_rows]
    resolution_chunks=[{"citation_id":"","article_id":str(r["article_id"]),"source_id":str(r["article_id"]),"source_type":"resolved_ticket","tenant_id":str(r["tenant_id"]),"department_id":str(r["department_id"]),"department":r["department"],"title":"Prior resolved ticket","chunk_text":r["chunk_text"],"distance":float(r["distance"]),"similarity":float(r["similarity"]),"article_version":r["article_version"],"status":"approved","is_publishable":True} for r in resolution_rows]
    merged=sorted(kb_chunks+resolution_chunks,key=lambda c:c["similarity"],reverse=True)[:top_k]
    kb_i=res_i=0
    for chunk in merged:
        if chunk["source_type"]=="knowledge_base": kb_i+=1; chunk["citation_id"]=f"KB-{kb_i:03d}"
        else: res_i+=1; chunk["citation_id"]=f"RT-{res_i:03d}"
    return {"retrieved_chunks":merged}

async def draft_node(state:TicketState)->dict:
    try:
        result=await asyncio.wait_for(get_llm_provider(_LLM_PROVIDER).generate_grounded_draft({"subject":state["subject"],"description":state["description"],"department":state.get("department"),"attachment_text":state.get("attachment_text",""),"attachment_text_is_untrusted":True},state.get("retrieved_chunks",[]),{"article_version":state.get("article_version","1.0")}),timeout=_LLM_TIMEOUT_SECONDS)
        if result.error or not result.content or not result.content.draft_text.strip(): return {"generation_status":"failed","generation_error":result.error or "Empty structured draft"}
        return {"draft_reply":result.content.draft_text,"citations":[c.model_dump() for c in result.content.citations],"insufficient_evidence":result.content.insufficient_evidence,"provider":result.provider,"model":result.model,"generated_at":result.generated_at.isoformat(),"generation_status":"generated","generation_error":None}
    except Exception as exc: return {"generation_status":"failed","generation_error":type(exc).__name__}

async def validate_citations_node(state:TicketState)->dict:
    evidence={x["citation_id"]:x for x in state.get("retrieved_chunks",[])}; inline=set(re.findall(r"\[((?:KB|RT)-\d{3})\]",state.get("draft_reply",""))); structured={x.get("citation_id","") for x in state.get("citations",[])}; invalid=set(); errors=[]
    for cid in inline|structured:
        item=evidence.get(cid)
        if not item: invalid.add(cid); errors.append(f"Unknown citation: {cid}"); continue
        if item["tenant_id"]!=state.get("tenant_id") or item["department_id"]!=state.get("department_id"): invalid.add(cid); errors.append(f"Out-of-scope citation: {cid}")
        if item.get("source_type","knowledge_base")=="knowledge_base" and item["article_version"]!=state.get("article_version","1.0"): invalid.add(cid); errors.append(f"Version mismatch: {cid}")
        if item.get("source_type")=="resolved_ticket" and not item.get("article_version"): invalid.add(cid); errors.append(f"Resolution version missing: {cid}")
        if item["status"]!="approved" or not item["is_publishable"] or not item["chunk_text"].strip(): invalid.add(cid); errors.append(f"Unpublishable citation: {cid}")
    missing_ids=structured-inline
    if missing_ids: errors.append("Structured citations missing from draft")
    insufficient=bool(state.get("insufficient_evidence"))
    if state.get("draft_reply") and not insufficient and not inline: errors.append("Technical draft has no citations")
    valid=not errors and state.get("generation_status")=="generated"
    checkable=[part.strip() for part in re.split(r"\n+|(?<=\])\s+(?=[A-Z])",state.get("draft_reply",""))
               if len(re.findall(r"\w+",part))>=3 and not part.strip().lower().startswith("development evidence draft")]
    uncited=[part[:300] for part in checkable if not re.search(r"\[(?:KB|RT)-\d{3}\]",part)]
    cited=len(checkable)-len(uncited)
    coverage=round(cited/len(checkable),4) if checkable else (1.0 if insufficient else 0.0)
    if uncited and not insufficient: errors.append("One or more factual or procedural claims have no citation");valid=False
    return {"citation_validation":{"valid":valid,"overall_status":"valid" if valid else "invalid","valid_citation_ids":sorted((inline|structured)-invalid),"invalid_citation_ids":sorted(invalid),"missing_citation_ids":sorted(missing_ids),"uncited_claim_warnings":uncited,"validation_errors":errors,"insufficient_evidence":insufficient,"citation_coverage":coverage,"unsupported_claim_count":len(uncited)},"generation_status":"ready" if valid else "failed_validation"}

async def validate_grounding_node(state:TicketState)->dict:
    result=validate_grounding(state.get("draft_reply",""),state.get("retrieved_chunks",[]),state.get("citation_validation",{}))
    return {"grounding_validation":result,"generation_status":"blocked_validation" if result["blocked"] else state.get("generation_status","ready")}

async def confidence_node(state:TicketState)->dict:
    """Calculate independent confidence from real pipeline signals.

    This intentionally uses the promoted logistic-regression artifact when one is
    available and the project's deterministic fallback otherwise. It never asks
    the draft-generating LLM to rate its own answer.
    """
    chunks=state.get("retrieved_chunks",[])
    scores=sorted((float(item.get("similarity",0)) for item in chunks),reverse=True)
    citation=state.get("citation_validation",{})
    grounding=state.get("grounding_validation",{})
    grounding_value={"Grounded":1.0,"Partially Grounded":.5}.get(grounding.get("overall_status"),0.0)
    entities=state.get("technical_entities",[])
    entity_quality=sum(float(item.get("confidence",0)) for item in entities)/len(entities) if entities else 0.0
    words=len((state.get("description") or "").split())
    ocr_quality=float(state.get("ocr_confidence")) if state.get("ocr_confidence_available") and state.get("ocr_confidence") is not None else 1.0
    features={
        "classification_probability":float(state.get("classification_probability",state.get("initial_confidence_score",.5))),
        "classification_margin":float(state.get("classification_margin",0)),
        "retrieval_similarity":scores[0] if scores else 0.0,
        "retrieval_score_gap":scores[0]-scores[1] if len(scores)>1 else 0.0,
        "citation_coverage":float(citation.get("citation_coverage",0)),
        "valid_evidence_count":len({item.get("citation_id") for item in chunks if item.get("citation_id")}),
        "ocr_quality":ocr_quality,
        "description_completeness":min(1.0,words/50),
        # Existing artifacts use one draft-validation feature. Blend the actual
        # grounding outcome and entity quality without changing their schema.
        "draft_validation":round(.75*grounding_value+.25*entity_quality,4),
        "entity_extraction_quality":round(entity_quality,4),
        "grounding_score":grounding_value,
    }
    score,version,trained=predict_confidence(features)
    low=float(state.get("low_confidence_threshold",.55));high=float(state.get("high_confidence_threshold",.80))
    band="high" if score>=high else "low" if score<low else "borderline"
    return {"confidence_score":score,"confidence_band":band,"confidence_features":features,
            "confidence_model_version":version,"confidence_provider":"logistic_regression" if trained else "deterministic_fallback",
            "confidence_trained_artifact":trained,"fallback_used":not trained,
            "trace_metadata":{"low_threshold":low,"high_threshold":high,"trained_artifact":trained}}

async def human_review_gate_node(state:TicketState)->dict:
    grounding=state.get("grounding_validation",{}).get("overall_status")
    band=state.get("confidence_band","low")
    if grounding in {"Unsupported","Conflicting Evidence","Human Investigation Required"} or band=="low": decision="human_investigation_required"
    elif grounding=="Partially Grounded" or band=="borderline": decision="mandatory_review_warning"
    else: decision="normal_controlled_review"
    return {"human_review_decision":decision}
