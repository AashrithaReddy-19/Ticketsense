import asyncio, os, re
from pathlib import Path
import asyncpg
from dotenv import dotenv_values
from pgvector.asyncpg import register_vector
from ai.agents.llm_interface import get_llm_provider
from .state import TicketState

ROOT=Path(__file__).resolve().parents[2]; ARTIFACTS_DIR=Path(__file__).resolve().parents[1]/"models"/"artifacts"; _env=dotenv_values(ROOT/".env")
_MODEL_NAME=os.environ.get("EMBEDDING_MODEL") or _env.get("EMBEDDING_MODEL","sentence-transformers/all-MiniLM-L6-v2")
_DATABASE_URL=os.environ.get("DATABASE_URL") or _env.get("DATABASE_URL",""); _LLM_PROVIDER=os.environ.get("LLM_PROVIDER") or _env.get("LLM_PROVIDER","stub")
_LLM_TIMEOUT_SECONDS=float(os.environ.get("LLM_TIMEOUT_SECONDS") or _env.get("LLM_TIMEOUT_SECONDS","30"))
_MODEL_LOAD_TIMEOUT_SECONDS=float(os.environ.get("MODEL_LOAD_TIMEOUT_SECONDS") or _env.get("MODEL_LOAD_TIMEOUT_SECONDS","120"))
_embedding_model=None; _classifiers=None

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
    if not state.get("tenant_id") or not state.get("department_id"): raise ValueError("retrieve_node requires tenant_id and department_id")
    query=f"Subject: {state['subject']}\nDescription: {state['description']}"
    if state.get("attachment_text"):query+=f"\n<UNTRUSTED_ATTACHMENT_DATA>\n{state['attachment_text']}\n</UNTRUSTED_ATTACHMENT_DATA>"
    vector=await asyncio.wait_for(asyncio.to_thread(lambda:_get_embedding_model().encode(query).tolist()),timeout=_MODEL_LOAD_TIMEOUT_SECONDS); version=state.get("article_version","1.0")
    conn=await asyncpg.connect(_asyncpg_url(_DATABASE_URL)); await register_vector(conn)
    try:
        rows=await conn.fetch("""SELECT k.id article_id,k.tenant_id,k.department_id,d.name department,k.title,k.version article_version,k.status,k.is_publishable,e.chunk_text,e.embedding <=> $1 distance,1-(e.embedding <=> $1) similarity FROM embeddings e JOIN knowledge_base k ON k.id=e.knowledge_base_id JOIN departments d ON d.id=k.department_id WHERE k.tenant_id=$2::uuid AND k.department_id=$3::uuid AND k.status='approved' AND k.version=$4 AND k.is_publishable=true AND length(trim(k.content))>0 AND length(trim(e.chunk_text))>0 ORDER BY e.embedding <=> $1 LIMIT $5""",vector,state["tenant_id"],state["department_id"],version,top_k)
    finally: await conn.close()
    return {"retrieved_chunks":[{"citation_id":f"KB-{i:03d}","article_id":str(r["article_id"]),"tenant_id":str(r["tenant_id"]),"department_id":str(r["department_id"]),"department":r["department"],"title":r["title"],"chunk_text":r["chunk_text"],"distance":float(r["distance"]),"similarity":float(r["similarity"]),"article_version":r["article_version"],"status":r["status"],"is_publishable":r["is_publishable"]} for i,r in enumerate(rows,1)]}

async def draft_node(state:TicketState)->dict:
    try:
        result=await asyncio.wait_for(get_llm_provider(_LLM_PROVIDER).generate_grounded_draft({"subject":state["subject"],"description":state["description"],"department":state.get("department"),"attachment_text":state.get("attachment_text",""),"attachment_text_is_untrusted":True},state.get("retrieved_chunks",[]),{"article_version":state.get("article_version","1.0")}),timeout=_LLM_TIMEOUT_SECONDS)
        if result.error or not result.content or not result.content.draft_text.strip(): return {"generation_status":"failed","generation_error":result.error or "Empty structured draft"}
        return {"draft_reply":result.content.draft_text,"citations":[c.model_dump() for c in result.content.citations],"insufficient_evidence":result.content.insufficient_evidence,"provider":result.provider,"model":result.model,"generated_at":result.generated_at.isoformat(),"generation_status":"generated","generation_error":None}
    except Exception as exc: return {"generation_status":"failed","generation_error":type(exc).__name__}

async def validate_citations_node(state:TicketState)->dict:
    evidence={x["citation_id"]:x for x in state.get("retrieved_chunks",[])}; inline=set(re.findall(r"\[(KB-\d{3})\]",state.get("draft_reply",""))); structured={x.get("citation_id","") for x in state.get("citations",[])}; invalid=set(); errors=[]
    for cid in inline|structured:
        item=evidence.get(cid)
        if not item: invalid.add(cid); errors.append(f"Unknown citation: {cid}"); continue
        if item["tenant_id"]!=state.get("tenant_id") or item["department_id"]!=state.get("department_id"): invalid.add(cid); errors.append(f"Out-of-scope citation: {cid}")
        if item["article_version"]!=state.get("article_version","1.0"): invalid.add(cid); errors.append(f"Version mismatch: {cid}")
        if item["status"]!="approved" or not item["is_publishable"] or not item["chunk_text"].strip(): invalid.add(cid); errors.append(f"Unpublishable citation: {cid}")
    missing=structured-inline
    if missing: errors.append("Structured citations missing from draft")
    insufficient=bool(state.get("insufficient_evidence"))
    if state.get("draft_reply") and not insufficient and not inline: errors.append("Technical draft has no citations")
    valid=not errors and state.get("generation_status")=="generated"
    return {"citation_validation":{"valid":valid,"valid_citation_ids":sorted((inline&structured)-invalid),"invalid_citation_ids":sorted(invalid),"uncited_claim_warnings":sorted(missing),"validation_errors":errors,"insufficient_evidence":insufficient},"generation_status":"ready" if valid else "failed_validation"}
