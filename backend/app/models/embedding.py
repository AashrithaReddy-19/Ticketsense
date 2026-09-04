import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class Embedding(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "embeddings"

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)


class TicketResolutionEmbedding(Base, UUIDPKMixin, CreatedAtMixin):
    """Retrieval index for approved, resolved-ticket responses — a separate, reusable
    evidence source from curated knowledge-base articles. Only ever populated from a
    ticket's reviewer-approved `final_response` (never a draft, note, or unapproved
    text), and always scoped by tenant and department at query time."""
    __tablename__ = "ticket_resolution_embeddings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)
    source_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    reusable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
