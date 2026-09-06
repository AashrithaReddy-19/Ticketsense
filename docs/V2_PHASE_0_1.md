# TicketSense V2 — Phase 0 audit and Phase 1 governance

Audit date: 2026-09-05. Branch: `feature/ticketsense-v2-innovation`.

## Verified v1 baseline

| Check | Verified result |
|---|---|
| Release commit/tag | `4f61e56` / `ticketsense-enterprise-v1.0` |
| Worktree before V2 | Clean |
| Alembic after bringing the local DB current | `0025 (head)` |
| Backend | 166 passed |
| Frontend | 59 passed |
| TypeScript / lint | Passed / passed |
| Production build | Passed (79 modules) |

The initial local database was still at 0018 although the source and release tag contained
0025. Applying the committed migrations brought it to 0025 without deleting data. The
repository—not the prompt—was used as the source of truth.

## Existing-component map

- Authentication and authorization: JWT access tokens, rotating refresh cookies, CSRF,
  lockout, normalized role grants, capability checks and tenant/department visibility.
- AI workflow: persisted Release B pipeline stages, scoped pgvector retrieval, technical
  entity extraction, grounded drafting, claim/citation validation and an independent
  confidence fallback.
- Enterprise workflow: three public experiences, fail-closed resolution policy,
  deterministic weighted assignment, conversations, response versions, confirmation and
  reopen protection.
- Operational modules: playbooks, incidents, SLA, knowledge gaps, safe sandbox actions,
  prevention recommendations, analytics and audit.

V2 extends these tables and services. It does not replace or fork them into a demo-only
application.

## Architecture decisions

### ADR-V2-001: feature flags before high-risk innovations

All V2 innovations are registered disabled. Server-side evaluation applies, in order:
unknown-key fail-closed behavior, global kill switch, active window, recursive
prerequisites, most-specific tenant override and stable percentage rollout. Stable rollout
uses SHA-256 of feature key, tenant and user; it does not depend on process-random hashing.
Customers receive only `enabled`; authorized Admins receive the safe decision reason.

### ADR-V2-002: registry metadata never stores secrets

Provider/model rows store immutable identifiers and references such as
`env:LLM_API_KEY`. Values are supplied by environment variables or a future secret-manager
adapter. A partial unique index permits only one enabled champion per tenant, task and
environment. Promotion requires an approved evaluation and an enabled
`challenger_models` flag. Promotion/rollback is transactional and audited; no challenger or
shadow output is connected to customer publication.

### ADR-V2-003: measurements remain nullable when unavailable

`ai_usage_events` records observed latency, success, provider/model version and optional
provider-reported tokens/cost. Missing token counts or prices remain `NULL`; the UI says
“Unavailable.” This prevents a configured price estimate from being confused with an
invoice and prevents fake zero-cost claims for unknown providers.

### ADR-V2-004: capability bundles supplement, not bypass, RBAC

Bundles reuse the existing permission catalogue. Grants are tenant-scoped and resolved by
the same authentication response and backend dependency. Conflict declarations provide a
separation-of-duties control. Direct role grants remain compatible with v1.

## Threat/risk assessment

| Risk | Phase 1 control |
|---|---|
| Tenant enables another tenant's feature | Override target validation and tenant-filtered queries |
| Unstable percentage cohorts | SHA-256 stable bucket |
| Emergency feature cannot be stopped | Globally enforced kill switch with audit history |
| Prerequisite cycle | Cycle detection, fail closed |
| Admin reads secret credentials | Registry accepts reference names only; no secret-value field |
| Two production champions | Partial unique DB index plus row locking |
| Unevaluated model promoted | Approved-evaluation precondition and feature gate |
| Challenger changes ticket state | Phase 1 has no challenger inference/publication path |
| Fake cost/latency metrics | Persisted events only; unavailable values are explicit |
| Excessive Admin privilege | Separate feature/model/prompt/observability/bundle capabilities and conflict-aware bundles |

## Migration 0026

Adds:

- `feature_flags`, `feature_flag_overrides`, `feature_flag_audits`
- `provider_models`, `model_deployments`, `prompt_versions`
- `ai_usage_events`
- `capability_bundles`, `capability_bundle_permissions`, `user_capability_bundles`

It also adds granular permissions and the 14 requested V2 feature keys. Every feature
defaults to disabled. Downgrade drops only V2 Phase 1 tables.

## Phased file-level plan

1. Phase 1 (this change): `0026`, V2 governance models/services/router, measured RAG usage,
   Admin governance route, seed metadata, security and API/component tests.
2. Evaluation foundation: dataset/import registry and leakage-safe split service under
   `data/` and `backend/app/services/evaluation/`; additive 0027 migration.
3. Evaluation Lab: reproducible jobs, exact metric library, exports and Admin lab UI.
4. Calibration and deployment: candidate artifacts, minimum-sample gates, risk/coverage
   simulation and rollback integration.
5. Resolution Passport and counterfactuals: transactionally invoked from existing
   resolution services with customer-safe serializers.
6. GraphRAG/change correlation: PostgreSQL graph adapter, scoped traversals, incident
   hypotheses and blast-radius UI.
7. Shadow/challenger/red-team: isolated outputs and datasets; never connected to workflow
   mutation or publication.
8. Multimodal/connectors/realtime: honest provider adapters, low-risk connector contract,
   signed replay-safe webhooks, authorized SSE and polling fallback.
9. Knowledge conflicts/process mining/drift: resolution-blocking conflicts, event-derived
   variants and sufficiency-aware forecasts.
10. Production hardening: CI security gates, backup/recovery, observability, accessibility,
    performance and clean upgrade/downgrade verification.

## Current honest limitations

Phase 1 is a governance foundation. It does not claim that Evaluation Lab, Resolution
Passport, GraphRAG, shadow/challenger inference, red-team execution, advanced OCR,
production connectors, SSE, conflict detection or process mining are implemented. Their
flags remain disabled until their own tested server-side implementations exist.
