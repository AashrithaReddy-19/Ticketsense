import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin

class TicketAttachment(Base,UUIDPKMixin,CreatedAtMixin,UpdatedAtMixin):
    __tablename__="ticket_attachments"; __table_args__=(UniqueConstraint("ticket_id",name="uq_ticket_attachments_ticket"),)
    ticket_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("tickets.id",ondelete="CASCADE"),nullable=False,index=True)
    tenant_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("organizations.id"),nullable=False,index=True)
    original_filename:Mapped[str]=mapped_column(String(255),nullable=False)
    storage_key:Mapped[str]=mapped_column(String(255),nullable=False,unique=True)
    declared_mime_type:Mapped[str|None]=mapped_column(String(120))
    detected_mime_type:Mapped[str]=mapped_column(String(120),nullable=False)
    file_extension:Mapped[str]=mapped_column(String(10),nullable=False)
    file_size_bytes:Mapped[int]=mapped_column(BigInteger,nullable=False)
    sha256_checksum:Mapped[str]=mapped_column(String(64),nullable=False)
    status:Mapped[str]=mapped_column(String(30),nullable=False,default="uploaded")
    validation_status:Mapped[str]=mapped_column(String(30),nullable=False,default="valid")
    extraction_status:Mapped[str]=mapped_column(String(30),nullable=False,default="pending")
    extraction_method:Mapped[str|None]=mapped_column(String(30))
    extracted_text:Mapped[str|None]=mapped_column(Text)
    sanitized_text:Mapped[str|None]=mapped_column(Text)
    ocr_confidence:Mapped[float|None]=mapped_column(Float)
    ocr_confidence_available:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    page_count:Mapped[int|None]=mapped_column(Integer)
    character_count:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    truncated:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    processing_duration_ms:Mapped[int|None]=mapped_column(Integer)
    warnings:Mapped[list]=mapped_column(JSONB,default=list,nullable=False)
    error_code:Mapped[str|None]=mapped_column(String(60))
    error_summary:Mapped[str|None]=mapped_column(String(255))
    processed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
