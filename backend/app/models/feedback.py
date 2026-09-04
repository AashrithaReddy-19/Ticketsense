import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class Feedback(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("action IN ('accept','edit','reject','escalate')", name="ck_feedback_action"),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    edited_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Character-level edit distance between the reviewer's final text and the draft
    # it replaced, normalized to [0,1] — the "amount of text changed" feature the
    # controlled confidence-model retraining workflow (Phase 13) trains on.
    text_change_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
