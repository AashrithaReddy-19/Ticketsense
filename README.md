# TicketSense

TicketSense is an enterprise-grade, multi-tenant, multi-agent AI support intelligence platform that turns support tickets into explainable, evidence-grounded, confidence-aware resolutions while converting successful support interactions into organizational knowledge.

Development status: the secure Phase 1 foundation is actively being expanded with tenant-scoped queues, human review workflows, and audited ticket routing.

For the most consistent local setup, run TicketSense through Docker Compose so the API, pgvector database, migrations, seed data, and web application start together.

## Run locally

Requirements: Docker Desktop with Compose v2.

```bash
copy .env.example .env
docker compose up --build
```

- Web application: http://localhost:3000
- FastAPI/OpenAPI: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health
- Readiness check: http://localhost:8000/api/health/ready

Compose starts pgvector/PostgreSQL, applies all Alembic migrations, creates development accounts, loads the curated knowledge base, starts FastAPI, and serves the production React build.

## Demo accounts

All development accounts use `Demo@123`.

| Portal | Account |
|---|---|
| Customer | `customer@demo.com` |
| Support agent | `agent@demo.com` |
| Reviewer | `reviewer@demo.com` |
| Knowledge manager | `kbmanager@demo.com` |
| Team lead | `teamlead@demo.com` |
| System administrator | `sysadmin@demo.com` |
| Auditor | `auditor@demo.com` |

Legacy `manager@demo.com`, `admin@demo.com`, `aiadmin@demo.com`, `knowledge@demo.com`, and `security@demo.com` remain available for compatibility.

Never use these credentials outside local development.

## End-to-end resolution flow

1. JWT-authenticated customer submits a ticket.
2. Preprocessing detects and redacts PII from the AI-safe representation.
3. Specialized stages understand, classify, score priority/SLA, detect duplicates, retrieve evidence, propose root causes, validate policy and safety, calculate confidence, and select routing.
4. Retrieval is restricted by organization and department.
5. The decision gate selects auto-resolution eligibility, human review, or expert escalation. High-risk work is never automatically resolved.
6. Every agent decision, evidence item, action and safe explanation is persisted for resolution replay and observability.
7. Agent actions, customer feedback, incidents, knowledge gaps and generated articles feed the learning workflow.

The default deterministic provider keeps the complete workflow runnable without a paid API. `ai/agents/llm_interface.py` provides the configurable provider boundary for OpenAI-compatible, local, Gemini-compatible or Anthropic-compatible implementations.

## Main APIs

- `POST /api/auth/login`, `POST /api/auth/register`, `GET /api/auth/me`
- `POST /api/tickets`, `GET /api/tickets`, `GET /api/tickets/{id}`
- `POST /api/tickets/{id}/action`, `POST /api/tickets/{id}/feedback`
- `POST /api/tickets/{id}/attachment`, `GET /.../attachment`, `POST /.../attachment/process`, `GET /.../attachment/download`, `DELETE /.../attachment`
- `GET /api/tickets/{id}/ai-draft`, `POST /api/tickets/{id}/ai-draft/generate`
- `GET /api/tickets/{id}/ai-analysis`, `/evidence`, `/similar`, `/trace`
- `GET /api/knowledge`, article generation and approval endpoints
- `GET /api/analytics`, `/api/ai/metrics`, `/api/incidents`
- `GET /api/audit-logs`, `/api/notifications`, `/api/integrations`

All protected resources are scoped by the authenticated user's `tenant_id`. Role guards protect elevated operations.

## Project layout

```text
backend/       FastAPI, SQLAlchemy models, schemas, services, routers, tests
ai/            provider abstraction, LangGraph pipeline, embeddings and ML training
frontend/      React + TypeScript enterprise role-aware workspace
db/            Alembic migrations, organization/demo seed, curated knowledge
data/          privacy-safe synthetic ticket generation and import tools
docs/          architecture, research evaluation protocol, and weekly delivery notes
               (docs/WEEK6_GROUNDED_RAG.md, docs/WEEK7_ATTACHMENT_OCR.md,
               docs/PHASE_1_17_IMPLEMENTATION.md, ../CHANGELOG.md)
docker-compose.yml
```

## Research datasets

TicketSense keeps its evaluation sources explicit and separates them from application code. The repository uses three data groups:

- **Public IT-support ticket data** for non-commercial classification and routing research.
- **Synthetic knowledge-base articles** for SAP, Networking, Cloud and HR retrieval evaluation.
- **Public screenshots and system logs** for attachment/OCR and log-ingestion demonstrations.

See [`data/README.md`](data/README.md) for provenance, licenses, permitted use and reproducibility details. Dataset presence does not mean a model was pretrained by this project, and none of these evaluation files should be treated as confidential company data.

## Development checks

```bash
cd frontend
npm install
npm run build

cd ../backend
uv sync --extra dev
uv run pytest
```

For optional training and pgvector embedding tools, use `uv sync --extra ai`.

## Research positioning

Individual techniques such as classification, RAG and routing are established. TicketSense's contribution is their integrated, measurable decision workflow: cross-source evidence, multi-agent validation, risk-aware autonomy, contradiction handling, incident and knowledge-gap detection, resolution replay, and feedback-to-knowledge learning. See [research-evaluation.md](docs/research-evaluation.md) for the experiment matrix and leakage-safe evaluation protocol.

Release B's persisted explainable pipeline, entity rules, grounding limitations and
staff-only APIs are documented in [RELEASE_B_IMPLEMENTATION.md](docs/RELEASE_B_IMPLEMENTATION.md).

## Security notes

Short-lived JWT access tokens, rotating HTTP-only refresh cookies, hashed revocable sessions, CSRF double-submit protection, bcrypt, tenant/department checks, normalized RBAC, PII redaction, rate limiting, strict configured CORS, security headers and audit records are included. Change `JWT_SECRET_KEY`, database credentials, allowed origins and provider secrets before any non-local deployment. Set `COOKIE_SECURE=true` behind HTTPS. Secrets must remain server-side.

## Login troubleshooting

The observed browser message `Failed to fetch` occurred because the API container had exited with code 137 while nginx remained reachable. Rebuild/start with `docker compose up --build -d`, then use `docker compose ps` and `docker compose logs api --tail 200`. The production frontend is compiled with `VITE_API_URL=http://localhost:8000`; this is intentionally the browser-visible host URL, not the Docker-internal service name.

Migration startup order is database health -> Alembic head -> idempotent seed -> knowledge load -> API -> API readiness -> web. Migration `0005` adds normalized roles, permissions, mappings, scoped user roles, and hashed refresh sessions. Migration `0006` adds persistent failed-login counters and timed account lockouts. Migration `0007` adds assignment, triage, review metadata, immutable human reviews, queue indexes, and an idempotent audited repair for legacy unrouted tickets. The API periodically deletes sessions expired for more than seven days.

Staff queues are available through `/api/queues/{queue_type}`. Agent queue types are `assigned`, `department_triage`, `general_triage`, `all`, and `escalated`; reviewers use `review`, and team leads use department-scoped `all`/`escalated`. Ticket list, queue, and direct-ID access share the same tenant/ownership/department visibility policy.

Docker validation commands:

```powershell
docker compose up --build -d
docker compose ps
docker compose exec api alembic current
docker compose exec api pytest -q
docker compose build web
Invoke-RestMethod http://localhost:8000/api/health/ready
```
