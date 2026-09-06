"""V2 Phase 7: tenant-isolated dependency graph (graph_nodes, graph_edges)

Revision ID: 0032
Revises: 0031
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE graph_nodes ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "node_type varchar(30) NOT NULL, external_id uuid NOT NULL, label varchar(300) NOT NULL, "
        "attributes jsonb NOT NULL DEFAULT '{}'::jsonb, source_record varchar(60) NOT NULL, "
        "confirmed boolean NOT NULL DEFAULT false, first_seen timestamptz NOT NULL, last_seen timestamptz NOT NULL, "
        "created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_graph_node_identity UNIQUE(tenant_id, node_type, external_id), "
        "CONSTRAINT ck_graph_nodes_type CHECK(node_type IN ('ticket','department','incident','playbook','knowledge_article','customer','error_code')))",
        "CREATE INDEX ix_graph_nodes_tenant_type ON graph_nodes(tenant_id, node_type)",
        "CREATE TABLE graph_edges ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
        "source_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE, "
        "target_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE, "
        "edge_type varchar(40) NOT NULL, confidence numeric(5,4), provenance text, "
        "confirmed boolean NOT NULL DEFAULT false, source_record varchar(60) NOT NULL, "
        "first_seen timestamptz NOT NULL, last_seen timestamptz NOT NULL, "
        "created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_graph_edge_identity UNIQUE(tenant_id, source_node_id, target_node_id, edge_type), "
        "CONSTRAINT ck_graph_edges_type CHECK(edge_type IN ('routed_to','submitted_by','clustered_into','applies_playbook','cites','extracted_error_code')))",
        "CREATE INDEX ix_graph_edges_tenant_source ON graph_edges(tenant_id, source_node_id)",
        "CREATE INDEX ix_graph_edges_tenant_target ON graph_edges(tenant_id, target_node_id)",
    ]
    for statement in statements:
        op.execute(statement)

    permission_codes = ("graph:read", "graph:manage")
    for code in permission_codes:
        op.execute(f"INSERT INTO permissions(code) VALUES ('{code}') ON CONFLICT DO NOTHING")
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) SELECT r.id,p.id FROM roles r CROSS JOIN permissions p "
        "WHERE (r.name='system_admin' AND p.code IN ('graph:read','graph:manage')) "
        "OR (r.name='support_agent' AND p.code = 'graph:read') "
        "OR (r.name='reviewer' AND p.code = 'graph:read') "
        "OR (r.name='team_lead' AND p.code IN ('graph:read','graph:manage')) "
        "OR (r.name='auditor' AND p.code = 'graph:read') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in ("graph_edges", "graph_nodes"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('graph:read','graph:manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('graph:read','graph:manage')")
