from typing import TypedDict


class RetrievedChunk(TypedDict):
    title: str
    chunk_text: str
    distance: float
    similarity: float
    article_version: str


class TicketState(TypedDict, total=False):
    tenant_id: str
    subject: str
    description: str

    department: str
    article_version: str
    priority: str
    sentiment: str

    retrieved_chunks: list[RetrievedChunk]

    draft_reply: str
    confidence_score: float
