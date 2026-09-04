"""Week 6 evidence-grounded LangGraph pipeline."""
from datetime import datetime,timezone
from time import monotonic
from langgraph.graph import END,START,StateGraph
from .nodes import attachment_or_text_node,classify_node,confidence_node,draft_node,human_review_gate_node,intake_node,priority_node,retrieve_node,route_node,technical_entity_node,validate_citations_node,validate_grounding_node
from .state import TicketState
PIPELINE_VERSION="release-b-1.0"

class PipelineStageError(RuntimeError):
    def __init__(self,stage_name:str,sequence_number:int,cause:Exception,started_at:str,duration_ms:int,completed_trace:list[dict]):
        super().__init__(type(cause).__name__)
        self.stage_name=stage_name;self.sequence_number=sequence_number;self.started_at=started_at
        self.duration_ms=duration_ms;self.error_category=type(cause).__name__
        # The trace contains safe summaries only. Keeping it on the structured
        # exception lets persistence retain stages completed before a failure.
        self.completed_trace=completed_trace

def _instrument(name,node,sequence):
    async def wrapped(state):
        started_at=datetime.now(timezone.utc);started=monotonic()
        try: updates=await node(state)
        except Exception as exc: raise PipelineStageError(name,sequence,exc,started_at.isoformat(),round((monotonic()-started)*1000),list(state.get("stage_trace",[]))) from exc
        completed_at=datetime.now(timezone.utc)
        safe_keys=sorted(key for key in updates if key not in {"draft_reply","retrieved_chunks","citations","processed_text"})
        fallback=bool(updates.get("fallback_used",False))
        failed=updates.get("generation_status") in {"failed","failed_validation","blocked_validation"}
        status="fallback" if fallback else "failed" if failed else "completed"
        return {**updates,"stage_trace":[{"stage_name":name,"sequence_number":sequence,"status":status,"input_summary":f"{len(state)} state fields available","output_summary":f"Updated: {', '.join(safe_keys) or 'stage status'}","provider_name":updates.get("provider") or updates.get("confidence_provider") or "deterministic","provider_version":updates.get("model") or updates.get("confidence_model_version") or PIPELINE_VERSION,"confidence":updates.get("confidence_score"),"started_at":started_at.isoformat(),"completed_at":completed_at.isoformat(),"duration_ms":round((monotonic()-started)*1000),"fallback_used":fallback,"metadata":updates.get("trace_metadata",{})}]} 
    return wrapped
_builder=StateGraph(TicketState)
_stages=(("intake",intake_node),("attachment_or_text",attachment_or_text_node),("technical_entity",technical_entity_node),("classify",classify_node),("priority",priority_node),("route",route_node),("retrieve",retrieve_node),("draft",draft_node),("validate_citations",validate_citations_node),("validate_grounding",validate_grounding_node),("confidence",confidence_node),("human_review_gate",human_review_gate_node))
for sequence,(name,node) in enumerate(_stages,1): _builder.add_node(name,_instrument(name,node,sequence))
_builder.add_edge(START,"intake")
for (before,_),(after,__) in zip(_stages,_stages[1:]): _builder.add_edge(before,after)
_builder.add_edge("human_review_gate",END)
graph=_builder.compile()
