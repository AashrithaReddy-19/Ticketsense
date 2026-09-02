from typing import Any, TypedDict

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
