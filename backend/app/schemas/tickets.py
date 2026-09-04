from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    subject: str = Field(min_length=4, max_length=255)
    description: str = Field(min_length=10, max_length=10000)
    category: str | None = None
    product: str | None = None
    severity: str | None = None
    environment: str | None = None
    error_message: str | None = None


class DescriptionAssistRequest(BaseModel):
    subject: str = Field(min_length=4, max_length=255)
    description: str = Field(min_length=10, max_length=4000)


class DescriptionAssistResponse(BaseModel):
    original: str
    suggested: str
    missing_information_questions: list[str]
    mode: str


class Evidence(BaseModel):
    title: str
    excerpt: str
    score: float
    source: str


class TicketPublic(BaseModel):
    id: UUID
    subject: str
    description: str
    status: str
    category: str | None = None
    required_specialization: str | None = None
    resolution_type: str | None = None
    priority: str | None
    sentiment: str | None
    department_id: UUID | None
    department_name: str | None = None
    assignee_id: UUID | None = None
    ai_draft_reply: str | None
    final_response: str | None = None
    final_responder_name: str | None = None
    approved_at: datetime | None = None
    resolved_at: datetime | None = None
    public_status_message: str | None = None
    confidence_score: float | None
    analysis: dict = Field(default_factory=dict)
    sla_due_at: datetime | None = None
    reopened_count: int = 0
    created_at: datetime
    updated_at: datetime


class TicketAction(BaseModel):
    action: str
    response: str | None = None
    reason: str | None = None


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    resolved: bool = True
