
# TicketSense

### Enterprise Multi-Agent AI Support Intelligence Platform

**Live Application:** [TicketSense on Vercel](https://ticketsense-beryl.vercel.app)

**Source Code:** [GitHub Repository](https://github.com/AashrithaReddy-19/Ticketsense)

**Technology:** Python, FastAPI, React, TypeScript, LangGraph, LangChain, PostgreSQL, pgvector, Docker

**Status:** Active Development — V2

---

## Project Overview

TicketSense is an enterprise-grade, multi-tenant, multi-agent AI support intelligence platform designed to transform traditional support ticket management into an intelligent, explainable, evidence-grounded and confidence-aware resolution system.

The platform combines AI-powered classification, intelligent routing, Retrieval-Augmented Generation (RAG), evidence validation, confidence scoring, human-in-the-loop review, analytics and organizational knowledge management.

TicketSense aims to reduce manual support operations while maintaining transparency, security, human oversight and accountability in automated decisions.

The preserved V1 release is tagged `ticketsense-enterprise-v1.0`.

V2 development is active on `feature/ticketsense-v2-innovation`.

[View V2 Architecture and Governance](docs/V2_PHASE_0_1.md)

---

## Live Deployment

### Access the Application

**https://ticketsense-beryl.vercel.app**

The application frontend is hosted on Vercel.

For running the complete application stack, including the backend, AI services and pgvector database, use the Docker Compose setup described below.

The public deployment URL does not by itself establish that every backend and AI feature is operational in production.

---

## Key Features

### 1. Intelligent Ticket Management

- Automated ticket classification
- Priority and severity assessment
- SLA-aware ticket processing
- Department-based intelligent routing
- Duplicate ticket detection
- Ticket assignment and escalation
- Ticket status monitoring
- Role-aware ticket queues

### 2. Multi-Agent AI Architecture

TicketSense coordinates specialized stages through a multi-agent decision pipeline.

Core capabilities include:

- Ticket understanding and classification
- Priority and SLA evaluation
- Similarity and duplicate detection
- Knowledge retrieval
- Root-cause proposal
- Response generation
- Evidence and policy validation
- Confidence estimation
- Human review and escalation

### 3. Retrieval-Augmented Generation

- Knowledge-base ingestion
- Semantic document retrieval
- Sentence Transformer embeddings
- PostgreSQL pgvector similarity search
- Context-aware answer generation
- Evidence-linked response drafts
- Grounding and citation verification

### 4. Confidence-Aware AI Decisions

- Confidence scoring from pipeline signals
- Unsupported-claim detection
- Grounding assessment
- Risk-based decision handling
- Human review for uncertain responses
- Escalation for high-risk requests

### 5. Human-in-the-Loop Review

- AI-generated response review
- Human approval and correction
- Reviewer queues
- Escalation workflows
- Review history
- Audited human decisions

### 6. Enterprise Dashboards

- Customer ticket management
- Support agent workspace
- Reviewer workspace
- Knowledge management
- Team lead monitoring
- System administration
- Audit and analytics views

### 7. Knowledge Management

- Centralized support knowledge base
- Knowledge article generation workflows
- Article approval
- Knowledge-gap identification
- Feedback-based knowledge improvement

### 8. Security and Governance

- Multi-tenant isolation
- Role-based access control
- JWT authentication
- PII redaction
- Department-level access restrictions
- Secure session handling
- Audit logging
- Rate limiting
- CSRF protection

---

## Technology Stack

| Component | Technologies |
|---|---|
| Frontend | React, TypeScript |
| Backend | Python, FastAPI |
| AI Orchestration | LangGraph, LangChain |
| Embeddings | Sentence Transformers |
| Database | PostgreSQL |
| Vector Search | pgvector |
| Authentication | JWT, RBAC |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Containerization | Docker, Docker Compose |
| Frontend Hosting | Vercel |
| Backend Testing | Pytest |
| API Documentation | FastAPI OpenAPI |

### AI Provider Support

The configurable AI provider boundary is implemented in:

`ai/agents/llm_interface.py`

The architecture accommodates:

- Deterministic development provider
- OpenAI-compatible providers
- Anthropic-compatible providers
- Gemini-compatible providers
- Local model implementations

The deterministic provider enables local workflow execution without requiring a paid AI API.

---

## System Architecture

```text
                   Customer / User
                         |
                         v
                  React Frontend
                         |
                         v
                    FastAPI API
                         |
                         v
                  Authentication
                    JWT + RBAC
                         |
                         v
                 Ticket Processing
                         |
                         v
                 Multi-Agent System
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     Classification   Priority      Duplicate
        Agent          Agent        Detection
          |              |              |
          +--------------+--------------+
                         |
                         v
                  RAG Retrieval
                         |
                         v
                Knowledge Base
                 PostgreSQL +
                   pgvector
                         |
                         v
                 Response Drafting
                         |
                         v
                Evidence Validation
                         |
                         v
                 Confidence Scoring
                         |
                         v
                    Decision Gate
                         |
              +----------+----------+
              |                     |
              v                     v
       Eligible Automation     Human Review /
                                Escalation
              |                     |
              +----------+----------+
                         |
                         v
                  Ticket Resolution
                         |
                         v
                 Audit and Feedback
                         |
                         v
                 Knowledge Learning
```

---

## End-to-End Ticket Resolution Workflow

1. A JWT-authenticated customer submits a support ticket.

2. Ticket preprocessing detects and redacts sensitive information from the AI-safe representation.

3. Specialized agents classify the request, estimate priority, evaluate SLA requirements and identify duplicate tickets.

4. Relevant knowledge articles are retrieved using organization- and department-scoped retrieval.

5. The AI pipeline prepares a response using retrieved evidence.

6. Evidence validation checks the generated response for unsupported or inconsistent claims.

7. Confidence scoring evaluates the reliability of the proposed response.

8. The decision gate determines automation eligibility, human review or expert escalation.

9. High-risk requests are not automatically resolved.

10. Agent decisions, supporting evidence, review actions and resolution histories are persisted for auditability.

11. Feedback, incidents, knowledge gaps and approved knowledge articles contribute to continuous improvement.

---

## User Roles

| Role | Responsibilities |
|---|---|
| Customer | Submit and monitor support tickets |
| Support Agent | Manage assigned tickets and resolutions |
| Reviewer | Review AI-generated drafts |
| Knowledge Manager | Maintain organizational knowledge |
| Team Lead | Monitor queues and escalations |
| System Administrator | Manage users and system settings |
| Auditor | Inspect audit records and decisions |

Access is controlled through tenant, department and role permissions.

---

## Run Locally

### Prerequisites

- Git
- Docker Desktop
- Docker Compose v2

### Step 1 — Clone Repository

```bash
git clone https://github.com/AashrithaReddy-19/Ticketsense.git
cd Ticketsense
```

### Step 2 — Configure Environment

Windows:

```powershell
copy .env.example .env
```

Linux / macOS:

```bash
cp .env.example .env
```

Update the environment configuration as needed.

### Step 3 — Start Application

```bash
docker compose up --build
```

Docker Compose handles:

- PostgreSQL and pgvector startup
- Alembic migrations
- Development account seeding
- Curated knowledge-base loading
- FastAPI backend startup
- API readiness checks
- React web application startup

### Local Access

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| FastAPI Documentation | http://localhost:8000/docs |
| Health Check | http://localhost:8000/api/health |
| Readiness Check | http://localhost:8000/api/health/ready |

---

## Demo Accounts

The following credentials are for the seeded local development environment.

**Development Password:** `Demo@123`

| Portal | Account |
|---|---|
| Customer | customer@demo.com |
| Support Agent | agent@demo.com |
| Reviewer | reviewer@demo.com |
| Knowledge Manager | kbmanager@demo.com |
| Team Lead | teamlead@demo.com |
| System Administrator | sysadmin@demo.com |
| Auditor | auditor@demo.com |

Legacy compatibility accounts:

- manager@demo.com
- admin@demo.com
- aiadmin@demo.com
- knowledge@demo.com
- security@demo.com

**Important:** Never use demo credentials outside local development.

---

## Main API Endpoints

### Authentication

```http
POST /api/auth/login
POST /api/auth/register
GET  /api/auth/me
```

### Ticket Management

```http
POST /api/tickets
GET  /api/tickets
GET  /api/tickets/{id}

POST /api/tickets/{id}/action
POST /api/tickets/{id}/feedback
```

### AI Drafts and Analysis

```http
GET  /api/tickets/{id}/ai-draft
POST /api/tickets/{id}/ai-draft/generate

GET /api/tickets/{id}/ai-analysis
GET /api/tickets/{id}/evidence
GET /api/tickets/{id}/similar
GET /api/tickets/{id}/trace
```

### Other Services

```http
GET /api/knowledge
GET /api/analytics
GET /api/ai/metrics
GET /api/incidents
GET /api/audit-logs
GET /api/notifications
GET /api/integrations
```

### Ticket Queues

```http
GET /api/queues/{queue_type}
```

Supported queue categories include:

- assigned
- department_triage
- general_triage
- all
- escalated
- review

Available queues depend on the authenticated user's permissions.

---

## Project Structure

```text
Ticketsense/
|
|-- backend/
|   |-- FastAPI routers
|   |-- SQLAlchemy models
|   |-- Schemas
|   |-- Services
|   |-- Authentication
|   |-- Tests
|
|-- ai/
|   |-- Provider abstraction
|   |-- LangGraph pipeline
|   |-- Embeddings
|   |-- ML training utilities
|
|-- frontend/
|   |-- React application
|   |-- TypeScript components
|   |-- Role-aware workspace
|
|-- db/
|   |-- Alembic migrations
|   |-- Organization seed
|   |-- Demo users
|   |-- Curated knowledge
|
|-- data/
|   |-- Synthetic ticket generation
|   |-- Dataset import tools
|   |-- Research datasets
|
|-- docs/
|   |-- Architecture
|   |-- Research evaluation
|   |-- Governance
|   |-- Implementation records
|
|-- .env.example
|-- docker-compose.yml
|-- CHANGELOG.md
|-- README.md
```

---

## Research and Evaluation

TicketSense also supports research into confidence-based review of AI-generated support responses.

### Research Paper

**When Grounded Answers Are Wrong: Evaluating Confidence-Based Review of RAG-Drafted Support Tickets**

### Research Problem

Retrieval-Augmented Generation can produce responses containing citations while still answering the wrong support issue.

This can occur when the retrieved knowledge article is related to the ticket topic but does not support the required resolution.

The research investigates whether confidence-based review can identify these incorrect or insufficiently grounded drafts.

### Research Objectives

- Evaluate RAG-generated support responses.
- Investigate retrieval and grounding failures.
- Measure claim-evidence consistency.
- Assess confidence-based review mechanisms.
- Identify unsupported response claims.
- Analyze the effect of missing relevant knowledge.
- Compare review decisions against evaluation labels.

### Research Dataset

The associated research materials describe:

- 1,775 synthetic support tickets
- 596 underlying scenarios
- 355 scenarios involving withheld relevant knowledge articles
- Evaluation labels generated using an LLM judge
- Confidence assessment using 31 pipeline signals

These values describe the research experiment and should not be interpreted as production deployment metrics.

### Dataset Categories

1. Public IT-support ticket data for classification and routing research.
2. Synthetic knowledge-base articles across SAP, Networking, Cloud and HR.
3. Public screenshots and system logs for attachment and OCR demonstrations.

Dataset provenance, licensing and usage restrictions are documented in:

[data/README.md](data/README.md)

### Research Contribution

TicketSense does not claim that individual methods such as RAG, classification or routing are new.

The contribution is the integration and evaluation of a confidence-aware multi-agent support workflow combining:

- Cross-source evidence
- Grounded response drafting
- Claim validation
- Confidence estimation
- Risk-aware automation
- Human review
- Decision replay
- Feedback-driven knowledge improvement

Additional details:

[Research Evaluation Protocol](docs/research-evaluation.md)

---

## Security Architecture

The project includes:

- Short-lived JWT access tokens
- Rotating HTTP-only refresh cookies
- Hashed, revocable sessions
- CSRF double-submit protection
- bcrypt password hashing
- Tenant and department checks
- Normalized role-based access control
- PII redaction
- Rate limiting
- Configured CORS
- Security headers
- Audit records
- Failed-login counters
- Timed account lockouts

Before non-local deployment, configure:

- JWT_SECRET_KEY
- Database credentials
- Allowed origins
- AI provider secrets
- HTTPS
- Secure cookie settings

Set `COOKIE_SECURE=true` when serving behind HTTPS.

Secrets must remain server-side.

---

## Development and Testing

### Frontend

```bash
cd frontend
npm install
npm run build
```

### Backend

```bash
cd backend
uv sync --extra dev
uv run pytest
```

### Optional AI Dependencies

```bash
uv sync --extra ai
```

### Docker Validation

```bash
docker compose up --build -d
docker compose ps
docker compose exec api alembic current
docker compose exec api pytest -q
docker compose build web
```

### API Health Check

```powershell
Invoke-RestMethod http://localhost:8000/api/health/ready
```

---

## Development Status

### V1 — Preserved Release

Tag:

`ticketsense-enterprise-v1.0`

### V2 — Active Development

Branch:

`feature/ticketsense-v2-innovation`

The ongoing development includes secure tenant-scoped queues, human review workflows, audited routing and extended governance capabilities.

The V2 foundation includes architecture and threat assessment work, database migration planning and documented feature-status tracking.

### Development Documentation

- [V2 Phase 0–1](docs/V2_PHASE_0_1.md)
- [Release B Implementation](docs/RELEASE_B_IMPLEMENTATION.md)
- [Week 6 Grounded RAG](docs/WEEK6_GROUNDED_RAG.md)
- [Week 7 Attachment OCR](docs/WEEK7_ATTACHMENT_OCR.md)
- [Implementation Documentation](docs/PHASE_1_17_IMPLEMENTATION.md)
- [Changelog](CHANGELOG.md)

---

## Database and Migration Notes

The application startup sequence is:

```text
Database Health
      |
      v
Alembic Migrations
      |
      v
Development Data Seed
      |
      v
Knowledge Base Load
      |
      v
FastAPI Startup
      |
      v
API Readiness
      |
      v
Web Application
```

Important migrations include:

- `0005` — Role and permission normalization and refresh sessions.
- `0006` — Failed-login tracking and account lockouts.
- `0007` — Ticket assignment, triage, review metadata and queue indexes.
- `0026` — Refer to the V2 governance documentation for its verified scope.

Expired sessions are periodically cleaned up.

---

## Troubleshooting

### Login Error — Failed to Fetch

A previously observed cause was the API container exiting while nginx remained reachable.

Restart the application:

```bash
docker compose up --build -d
```

Check container status:

```bash
docker compose ps
```

Inspect API logs:

```bash
docker compose logs api --tail 200
```

The documented local frontend build uses:

```env
VITE_API_URL=http://localhost:8000
```

This value is intended for the browser-accessible local backend.

A deployed frontend must use an appropriately configured, publicly reachable backend URL rather than a localhost URL.

---

## Application Links

**Live Application**

https://ticketsense-beryl.vercel.app

**GitHub Repository**

https://github.com/AashrithaReddy-19/Ticketsense

---

## Disclaimer

TicketSense is an academic and research-oriented enterprise AI support platform under active development.

Synthetic datasets and demo credentials are intended for controlled development and research use.

Automated AI-generated responses require appropriate verification, security controls and human oversight before deployment in sensitive enterprise environments.
