"""approved historical resolution retrieval source

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE ticket_resolution_embeddings("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        "tenant_id uuid NOT NULL REFERENCES organizations(id),"
        "department_id uuid NOT NULL REFERENCES departments(id),"
        "ticket_id uuid NOT NULL UNIQUE REFERENCES tickets(id) ON DELETE CASCADE,"
        "chunk_text text NOT NULL,"
        "embedding vector(384) NOT NULL,"
        "source_version varchar(20) NOT NULL DEFAULT '1.0',"
        "reusable boolean NOT NULL DEFAULT true,"
        "created_at timestamptz NOT NULL DEFAULT now(),"
        "CONSTRAINT ck_resolution_embeddings_nonempty CHECK(length(trim(chunk_text))>0))"
    )
    op.execute("CREATE INDEX ix_resolution_embeddings_scope ON ticket_resolution_embeddings(tenant_id,department_id) WHERE reusable=true")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ticket_resolution_embeddings")
