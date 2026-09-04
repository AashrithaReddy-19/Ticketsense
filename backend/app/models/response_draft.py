import uuid

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin


class ResponseDraft(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "response_drafts"
    __table_args__ = (
        UniqueConstraint("ticket_id", "version_number", name="uq_response_drafts_ticket_version"),
        CheckConstraint("author_type IN ('ai','engineer','reviewer')", name="ck_response_drafts_author_type"),
        CheckConstraint(
            "status IN ('generated','engineer_edited','submitted_for_review','changes_requested','reviewer_modified','approved','rejected','superseded')",
            name="ck_response_drafts_status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    creator_role: Mapped[str | None] = mapped_column(String(30))
    based_on_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("response_drafts.id"))
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    citation_validation_status: Mapped[str | None] = mapped_column(String(30))
    validation_details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TicketEvent(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "ticket_events"
    __table_args__ = (
        CheckConstraint("visibility IN ('internal','customer','both')", name="ck_ticket_events_visibility"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str | None] = mapped_column(String(30))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    actor_role: Mapped[str | None] = mapped_column(String(30))
    comment: Mapped[str | None] = mapped_column(Text)
    draft_version: Mapped[int | None] = mapped_column(Integer)
    old_assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    new_assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, default="internal")


class EngineerDepartment(Base, CreatedAtMixin):
    __tablename__ = "engineer_departments"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True)


class EngineerSpecialization(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "engineer_specializations"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
