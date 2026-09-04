"""knowledge-gap lifecycle: link approved articles to the retrieval corpus they publish

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_articles ADD COLUMN published_knowledge_base_id uuid "
        "REFERENCES knowledge_base(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE knowledge_articles ADD COLUMN rejected_reason text"
    )
    op.execute(
        "ALTER TABLE knowledge_articles ADD COLUMN source_signal varchar(60)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_articles DROP COLUMN IF EXISTS source_signal")
    op.execute("ALTER TABLE knowledge_articles DROP COLUMN IF EXISTS rejected_reason")
    op.execute("ALTER TABLE knowledge_articles DROP COLUMN IF EXISTS published_knowledge_base_id")
