-- Sample dev data. Run via `uv run python ../db/seed/run_seed.py` from backend/,
-- or `psql <DATABASE_URL> -f db/seed/seed.sql` directly.

INSERT INTO departments (name, description) VALUES
    ('SAP', 'SAP ERP: transactions, authorizations, batch jobs, master data'),
    ('Networking', 'VPN, Wi-Fi, DNS, firewall, and connectivity issues'),
    ('Payments', 'Payment processing, billing integrations, and transaction failures'),
    ('Cloud', 'Cloud infrastructure: access, storage, compute, and cost'),
    ('HR', 'Leave, payroll, benefits, and employee policy questions')
ON CONFLICT (name) DO NOTHING;

-- Dev-only login. hashed_password is a plain placeholder, NOT a real hash — replace once
-- auth is implemented in a later phase.
INSERT INTO users (email, full_name, role, public_role, hashed_password) VALUES
    ('admin@ticketsense.local', 'TicketSense Admin', 'admin', 'admin', 'CHANGE_ME_dev_placeholder')
ON CONFLICT (email) DO NOTHING;

-- Real knowledge_base content is authored under db/seed/knowledge_base/ and loaded via
-- db/seed/load_knowledge_base.py, not inserted here.
