"""secure ticket attachments

Revision ID: 0010
Revises: 0009
"""
from alembic import op
revision="0010"; down_revision="0009"; branch_labels=None; depends_on=None
def upgrade()->None:
    op.execute("""CREATE TABLE ticket_attachments(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,tenant_id uuid NOT NULL REFERENCES organizations(id),original_filename varchar(255) NOT NULL,storage_key varchar(255) NOT NULL UNIQUE,declared_mime_type varchar(120),detected_mime_type varchar(120) NOT NULL,file_extension varchar(10) NOT NULL,file_size_bytes bigint NOT NULL,sha256_checksum varchar(64) NOT NULL,status varchar(30) NOT NULL DEFAULT 'uploaded',validation_status varchar(30) NOT NULL DEFAULT 'valid',extraction_status varchar(30) NOT NULL DEFAULT 'pending',extraction_method varchar(30),extracted_text text,sanitized_text text,ocr_confidence double precision,ocr_confidence_available boolean NOT NULL DEFAULT false,page_count integer,character_count integer NOT NULL DEFAULT 0,truncated boolean NOT NULL DEFAULT false,processing_duration_ms integer,warnings jsonb NOT NULL DEFAULT '[]',error_code varchar(60),error_summary varchar(255),processed_at timestamptz,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),CONSTRAINT uq_ticket_attachments_ticket UNIQUE(ticket_id),CONSTRAINT ck_attachment_status CHECK(status IN ('uploaded','validating','processing','ready','rejected','failed')),CONSTRAINT ck_attachment_extraction_status CHECK(extraction_status IN ('pending','processing','ready','empty','failed')) )""")
    op.execute("CREATE INDEX ix_ticket_attachments_scope ON ticket_attachments(tenant_id,ticket_id)")
def downgrade()->None:
    op.execute("DROP INDEX IF EXISTS ix_ticket_attachments_scope"); op.execute("DROP TABLE IF EXISTS ticket_attachments")
