import operator
from typing import Annotated, Any, NotRequired, TypedDict

class RetrievedChunk(TypedDict):
    citation_id: str
    article_id: str
    tenant_id: str
    department_id: str
    department: str
    title: str
    chunk_text: str
    distance: float
    similarity: float
    article_version: str
    status: str
    is_publishable: bool
    # Present on every row; kept NotRequired only so older call sites building this
    # dict by hand (tests, fixtures) don't need updating for these additive fields.
    source_type: NotRequired[str]  # "knowledge_base" | "resolved_ticket"
    source_id: NotRequired[str]

class TicketState(TypedDict, total=False):
    ticket_id: str
    tenant_id: str
    department_id: str
    subject: str
    description: str
    attachment_id: str
    attachment_type: str
    extraction_status: str
    attachment_text: str
    extraction_method: str
    ocr_confidence: float | None
    ocr_confidence_available: bool
    extraction_warnings: list[str]
    attachment_truncated: bool
    department: str
    article_version: str
    priority: str
    sentiment: str
    routing_status: str
    retrieved_chunks: list[RetrievedChunk]
    draft_reply: str
    citations: list[dict[str, Any]]
    insufficient_evidence: bool
    provider: str
    model: str
    generated_at: str
    generation_status: str
    generation_error: str | None
    citation_validation: dict[str, Any]
    processed_text: str
    technical_entities: list[dict[str, Any]]
    grounding_validation: dict[str, Any]
    confidence_score: float
    initial_confidence_score: float
    classification_probability: float
    classification_margin: float
    low_confidence_threshold: float
    high_confidence_threshold: float
    confidence_band: str
    confidence_features: dict[str, Any]
    confidence_model_version: str
    confidence_provider: str
    confidence_trained_artifact: bool
    fallback_used: bool
    trace_metadata: dict[str, Any]
    human_review_decision: str
    stage_trace: Annotated[list[dict[str, Any]], operator.add]
