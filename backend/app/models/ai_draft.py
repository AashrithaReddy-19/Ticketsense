import uuid
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin

class AIDraft(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__="ai_drafts"
    __table_args__=(UniqueConstraint("ticket_id",name="uq_ai_drafts_ticket"),)
    tenant_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("organizations.id"),nullable=False,index=True)
    ticket_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("tickets.id",ondelete="CASCADE"),nullable=False,index=True)
    department_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("departments.id"),nullable=False,index=True)
    article_version:Mapped[str]=mapped_column(String(20),nullable=False,default="1.0")
    draft_text:Mapped[str|None]=mapped_column(Text)
    citations:Mapped[list]=mapped_column(JSONB,default=list,nullable=False)
    evidence:Mapped[list]=mapped_column(JSONB,default=list,nullable=False)
    provider:Mapped[str|None]=mapped_column(String(80))
    model:Mapped[str|None]=mapped_column(String(120))
    generation_status:Mapped[str]=mapped_column(String(40),nullable=False,default="pending")
    citation_validation_status:Mapped[str]=mapped_column(String(40),nullable=False,default="pending")
    validation_details:Mapped[dict]=mapped_column(JSONB,default=dict,nullable=False)
    generation_error:Mapped[str|None]=mapped_column(Text)
    insufficient_evidence:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    attempt_count:Mapped[int]=mapped_column(Integer,default=1,nullable=False)
