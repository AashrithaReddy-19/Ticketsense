# TicketSense master implementation baseline

This document is the required pre-implementation baseline for the enterprise specification. It distinguishes current working behavior from the target design; later phases must not be described as complete until their UI, API, persistence, authorization, audit, and tests work together.

## 1. Current-state architecture

```text
Browser -> React 18 / TypeScript / Vite -> FastAPI async API -> PostgreSQL 16 + pgvector
                                              |
                                              +-> deterministic local ticket intelligence
                                              +-> audit, notification, knowledge and incident records
```

Docker Compose currently starts PostgreSQL, the FastAPI service, and an nginx-served React SPA. Alembic applies schema changes and a repeatable Python seed creates demo users/data. JWT bearer authentication, bcrypt hashing, tenant IDs, department filtering, security headers, basic in-memory rate limiting, deterministic PII redaction, and audit rows exist. The `ai/` directory contains optional LangGraph, embedding, and classifier scaffolds, but these are not wired into the live API and are intentionally not claimed as production AI.

## 2. Gap analysis

| Area | Current implementation | Required gap |
|---|---|---|
| Identity | Access JWT and bcrypt | Refresh rotation/revocation, lockout, MFA/SSO extension |
| Authorization | Tenant checks, department filters, centralized canonical role permissions added in Phase 1 | Normalized roles/permissions/user-role scopes and exhaustive negative API tests |
| Roles | Canonical seven roles are accepted and seeded; legacy aliases remain compatible | Dedicated role dashboards/workflows for reviewer, manager, admin and auditor |
| Tickets | Create/list/detail, simple actions/history | Full state machine, messages, notes, assignments, attachments, SLA, escalations and feedback lifecycle |
| AI | Deterministic analysis and 19 named decision rows | Async retryable LangGraph execution, meaningful per-stage inputs/outputs, provider abstraction, calibration model |
| RAG | Tenant-filtered knowledge and deterministic keyword evidence | Authorized hybrid FTS/vector retrieval, version filters, reranking, ingestion security, evaluation |
| Governance | Audit rows and draft article approval | Immutable reviews, versioned knowledge lifecycle, retention and append-only enforcement |
| Frontend | Responsive authenticated workspace with role-aware navigation | Backend-derived permission route guards, TanStack Query, RHF/Zod, complete seven-role journeys and tests |
| Operations | Compose health check for DB/API endpoint, nginx | Redis worker, structured logs, CI, backup/restore and production monitoring |
| Testing | Small unit suite and production frontend build | Integration, migration, authorization, cross-tenant, frontend, E2E, fallback, load and AI evaluation suites |

External credentials are needed only for real LLM, email/chat/helpdesk, SSO, malware scanning, and secrets-manager adapters. Local deterministic mode remains the safe default and must label its outputs.

## 3. Final role-permission matrix

| Capability | Customer | Agent | Reviewer | Knowledge manager | Team lead | System admin | Auditor |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Own public tickets/messages/feedback | RW | Scoped R | Scoped R | - | Scoped R | - | R* |
| Department queue/internal notes | - | RW | R | - | RW | - | R* |
| Internal AI/evidence/confidence | - | RW | RW | Retrieval test | RW | Health only | R* |
| Human approval/review record | - | Submit | RW | - | Approve scoped | - | R* |
| Knowledge lifecycle | Published R | R/contribute | Flag gaps | RW/publish | Metrics | Configure | R* |
| Assignment/SLA/escalation | - | Scoped | Correct | - | RW | Configure | R* |
| Users/tenant/security/integrations | - | - | - | - | Delegated dept | RW | R* |
| Audit mutation | - | - | - | - | - | - | - |

`R*` means authorized read-only compliance scope, never unrestricted content by default. All access is additionally constrained by tenant, department, resource sensitivity, and explicit scope.

## 4. Proposed database schema

Keep existing `organizations` as the tenant table during compatibility migration. The normalized target groups are:

- Identity/scope: `tenants`, `tenant_settings`, `departments`, `users`, `roles`, `permissions`, `user_roles`, `feature_flags`.
- Ticket lifecycle: `categories`, `tickets`, `ticket_assignments`, `ticket_status_history`, `ticket_messages`, `internal_notes`, `attachments`, `sla_policies`, `sla_events`, `escalations`, `feedback`.
- AI/governance: `ai_runs`, `ai_stage_decisions`, `retrieved_evidence`, `response_drafts`, `human_reviews`, `model_versions`.
- Knowledge/operations: `knowledge_articles`, `knowledge_versions`, `knowledge_chunks`, `knowledge_gaps`, `incidents`, `incident_ticket_links`, `notifications`, `integrations`, `audit_events`.

All tenant-owned rows carry a non-null tenant UUID. Frequently edited records receive a version column for optimistic concurrency; lifecycle data uses soft deletion where legally appropriate, while review and audit records remain append-only. Composite indexes begin with tenant ID and include department/status/assignee/priority/SLA/date as applicable. Vector and full-text indexes apply only to publishable, versioned knowledge chunks.

## 5. API and frontend route map

Target API groups: `/api/auth`, `/users`, `/roles`, `/tenants`, `/departments`, `/tickets`, `/tickets/{id}/messages`, `/assignments`, `/transitions`, `/escalations`, `/reviews`, `/knowledge`, `/retrieval-tests`, `/ai-runs`, `/feedback`, `/incidents`, `/slas`, `/notifications`, `/analytics`, `/integrations`, `/audit-events`, plus `/api/health` and OpenAPI `/docs`.

Target UI routes: `/portal` (customer), `/agent`, `/review`, `/knowledge`, `/operations`, `/admin`, `/audit`, with a shared permission-shaped `/tickets/:id`. The shared detail view exposes public messages to customers and conditionally adds internal notes, evidence, AI decisions, reviews, SLA, and audit panels only when the server grants the corresponding permission.

## 6. Phase 1 implementation plan

1. Preserve Docker/PostgreSQL/FastAPI/React vertical slice and migration compatibility.
2. Establish canonical seven-role policy, retain explicit legacy aliases, seed all roles, and prevent customer/internal and cross-department leakage.
3. Normalize RBAC and scoped assignments in a following migration; return effective permissions from `/auth/me` and enforce route guards in React.
4. Add refresh-session rotation/revocation, login throttling/lockout, tenant settings, feature flags, and centralized immutable audit service.
5. Add API integration and negative authorization fixtures using two tenants and multiple departments.
6. Run Alembic upgrade/downgrade checks, backend tests, frontend type/build checks, Docker health checks, and update this baseline with measured results before Phase 2.

### Phase status

Phase 1 is **in progress**. Canonical policy, urgent response/query isolation, normalized RBAC migration `0005`, database-derived effective permissions, rotating HTTP-only refresh sessions, CSRF protection, logout/logout-all revocation, persistent login lockout migration `0006`, refresh-reuse revocation, scheduled expired-session cleanup, canonical seed accounts, frontend role guards, safe API-unavailable messaging, and database/pgvector readiness are implemented. Docker migration head, seven-account authentication, refresh rotation, logout rejection, 401/403 checks, and 8 backend tests are verified. Full browser automation, two-tenant/two-department fixtures, exhaustive resource authorization tests, frontend component/E2E tests, and complete reviewer/admin workflows remain. Phase 2 has not started.

Migration `0007` adds centralized ticket visibility, assigned/department/general/reviewer/team-lead queues, audited legacy routing repair, agent acceptance, and immutable reviewer decisions. The frontend agent, reviewer, and team-lead routes now consume these real APIs. Live verification proves ticket `25afd0c6-af25-4126-bdbe-88f389b7123b` is visible to its customer, assigned agent, department reviewer, and team lead while system administration has no queue access and customer AI fields remain redacted. The backend suite has 10 passing tests. A generated two-tenant/two-department test fixture matrix remains required before Phase 1 completion.

### Login incident root cause

The web and database containers were running while the API container had exited with code 137. Consequently the browser's configured `http://localhost:8000` endpoint had no listener and Fetch produced a network error. Rebuilding/restarting the API applied migrations `0004` and `0005`, reran the idempotent seed, and restored the real OAuth-form login. The frontend now translates transport failures into a safe backend-unavailable message rather than displaying the raw Fetch exception.
