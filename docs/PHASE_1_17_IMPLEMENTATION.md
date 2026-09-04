# Controlled workflow implementation reference (Phases 1–17)

Companion to `docs/MASTER_IMPLEMENTATION_BASELINE.md` (the pre-existing Phase 1
baseline) and `docs/architecture.md`. This document covers what the phase-ordered
enhancement pass added on top of that baseline: the approved-response workflow,
cross-role synchronization, assignment, retrieval, confidence modeling, evaluation
tooling, analytics, and the configurable LLM provider.

## 1. Ticket state-transition table

Deployed statuses (backend-enforced in `app/services/workflow.py:ALLOWED_TRANSITIONS`;
the frontend never decides validity, only reflects it):

| From | Allowed to |
|---|---|
| `submitted` | `processing`, `escalated` |
| `processing` | `classified`, `escalated` |
| `classified` | `routed`, `escalated` |
| `routed` | `assigned`, `escalated` |
| `assigned` | `in_progress`, `escalated` |
| `in_progress` | `pending_review`, `escalated` |
| `pending_review` | `changes_requested`, `approved`, `escalated` |
| `changes_requested` | `in_progress`, `pending_review`, `escalated` |
| `approved` | `resolved` |
| `resolved` | `reopened`, `closed` |
| `reopened` | `assigned`, `in_progress`, `escalated` |
| `escalated` | `assigned`, `in_progress`, `closed` |
| `closed` | `reopened` |

`approve_draft()` moves a ticket through `approved` → `resolved` atomically in one
call, persisting `final_response`/`final_response_draft_id`/`approved_at`/
`resolved_at` in the same transaction (`ck_tickets_resolved_has_response` makes it
impossible to be `resolved` without a response, at the database level).

## 2. Role-permission matrix (additions in this pass)

Extends — never replaces — `docs/MASTER_IMPLEMENTATION_BASELINE.md` §3.

| Capability | Customer | Support agent | Reviewer | Team lead | System admin | Auditor |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Save/submit response draft | – | Own assigned ticket | – | – | – | – |
| Approve / modify & approve / request changes / escalate | – | – | Yes | Yes (`review:manage`) | Yes | – |
| Assign / reassign engineer | – | – | Yes (`ticket:assign`) | Yes | Yes | – |
| View/edit engineer profiles | – | – | – | – | Yes (`user:manage`) | – |
| View engineer workload dashboard | – | – | – | Own department | All departments | – |
| Configure department confidence thresholds | – | – | – | – | Yes (`department:manage`) | – |
| View internal timeline / drafts / evidence | – | Yes | Yes | Yes | Yes | Read-only |
| View customer-safe timeline / final response | Own tickets | – | – | – | – | – |
| View analytics dashboard | – | Yes | Yes | Yes | Yes | – |
| Improve own ticket description (suggest-only) | Yes | – | – | – | – | – |

All access remains additionally scoped by tenant and department, as in the
existing baseline. See `backend/app/core/rbac.py` for the enforced source of
truth; `backend/tests/test_ticket_isolation_matrix.py` and
`test_resolution_retrieval_isolation.py` are the negative/isolation tests.

## 3. Database schema changes (migrations 0011–0015)

- **`response_drafts`**: immutable version history. `version_number` unique per
  ticket; `status` one of `generated/engineer_edited/submitted_for_review/
  changes_requested/reviewer_modified/approved/rejected/superseded`; `is_final`
  marks the one version that became the customer-visible response.
- **`ticket_events`**: append-only audit/timeline row per transition, with
  `visibility` (`internal`/`customer`/`both`), actor, old/new status, old/new
  assignee, draft version, correlation id and structured metadata.
- **`engineer_departments`**, **`engineer_specializations`**: many-to-many
  department membership and named specializations per engineer.
- **`tickets`** gains `final_response`, `latest_draft_id`,
  `final_response_draft_id`, `final_responder_id`, `final_approver_id`,
  `approved_at`, `resolved_at`, `public_status_message`, `assignment_reason`,
  `assigned_at`. `ck_tickets_resolved_has_response` enforces a response exists
  whenever `status` is `approved`/`resolved`.
- **`users`** gains `is_available`, `max_active_workload`, `last_assigned_at`.
- **`department_confidence_policies`**: versioned, tenant+department-scoped
  threshold rows (`low_threshold <= high_threshold`, both in `[0,1]`).
- **`pipeline_metrics`**: per-stage timing (`stage`, `duration_ms`, `success`,
  `error_category`, `trace_id`) for OCR, classification, routing, confidence
  scoring, and the combined retrieval/drafting stage.
- **`ticket_resolution_embeddings`**: the second retrieval source — one
  embedding row per resolved ticket's `final_response`, tenant+department
  scoped, `reusable` flag, never populated from anything but an approved
  final response.
- **`feedback.text_change_ratio`**: character-level edit distance between a
  reviewer's final text and the draft it replaced.

All migrations are additive and reversible (`downgrade()` provided in each
file); none rewrites or drops existing data outside of documented, narrow
backfills (e.g. `0012` moves a legacy `resolved` ticket with no response back
to `pending_review` rather than leaving an inconsistent row).

## 4. New/changed API endpoints

```
POST   /api/tickets/assist-description
GET    /api/tickets/{id}/timeline
GET    /api/tickets/{id}/drafts
POST   /api/tickets/{id}/drafts
POST   /api/tickets/{id}/assign
POST   /api/tickets/{id}/start-work
POST   /api/tickets/{id}/submit-for-review
POST   /api/tickets/{id}/review
POST   /api/tickets/{id}/escalate
POST   /api/tickets/{id}/reopen
GET    /api/departments/{id}/engineers
GET    /api/admin/engineers
POST   /api/admin/engineers
PATCH  /api/admin/engineers/{id}
GET    /api/admin/departments
GET    /api/workloads/engineers
GET    /api/admin/departments/{id}/confidence-policy
POST   /api/admin/departments/{id}/confidence-policy
GET    /api/analytics                 (response shape extended, additive fields only)
```

Every endpoint above authenticates via the existing JWT/cookie dependency,
enforces tenant isolation through `get_visible_ticket`/`scoped_ticket` or an
explicit `tenant_id` filter, and enforces role via `has_permission`/
`require_role`. See `backend/tests/test_synchronized_workflow.py`,
`test_operations_api.py` and `test_analytics_pipeline_metrics.py` for the
positive- and negative-authorization coverage.

## 5. Cross-role synchronization design

No message broker or WebSocket infrastructure existed to build on, so
synchronization is **configurable authenticated polling** through the same
authorized REST endpoints every view already calls — never a separate
subscription channel, so there is no additional surface to leak tenant/
department data through. `frontend/src/lib/useAutoRefresh.ts`:

- Polls at `VITE_SYNC_POLL_INTERVAL_MS` (default 15000ms) while the tab is
  `visible`; pauses entirely when hidden and re-fetches immediately on
  becoming visible again.
- Never applies optimistic state — every refresh re-fetches authoritative data
  and replaces local state with it.
- A `touchedResponse`/`touchedAssignment` guard in `TicketWorkspace.tsx`
  prevents a background poll from overwriting an engineer's or reviewer's
  in-progress, unsaved edit; the guard clears once that edit is actually
  saved, so display resumes tracking the server.
- Exposes a `live`/`syncing`/`error` status surfaced as a visible indicator
  (`<SyncIndicator>`) with a manual retry action, never a silent failure.
- Server-side, every mutation writes its `ticket_events`/audit rows inside the
  same transaction as the state change it describes — a client never
  polls into a partially-committed state.

## 6. Assignment algorithm (Phase 3)

`app/services/workflow.py:auto_assign_ticket`, invoked automatically when a
ticket is routed to a department:

1. Row-lock (`SELECT ... FOR UPDATE`) every active, available engineer in the
   ticket's tenant + department — this is what makes concurrent assignment
   requests safe against a stale-workload race.
2. For each candidate, count active tickets (`assigned/in_progress/
   pending_review/changes_requested/reopened/escalated`); exclude anyone at or
   over `max_active_workload`.
3. Rank remaining candidates by (specialization match first, then least active
   workload, then oldest `last_assigned_at`/lowest id as a deterministic
   tie-break).
4. Record the selection reason (`assignment_reason`) and a structured audit
   event including which criterion decided it.
5. A manual assignment (`POST /api/tickets/{id}/assign`, Team Lead/Admin/
   Reviewer only) is a no-op if the same engineer is already assigned, and is
   never silently overwritten by the automatic path — auto-assignment only
   runs once, at routing time, on a still-unassigned ticket.

## 7. Draft-version and audit model (Phase 5)

Every `response_drafts` row is create-only: `create_draft()` marks the
previous non-terminal version `superseded` and inserts a new row rather than
updating content in place, so the full edit history — AI draft, engineer
edits, reviewer modification, final approved version — is reconstructable.
`ticket_events` is the parallel append-only audit log; `visibility` controls
who can read a given row (`GET /api/tickets/{id}/timeline` filters server-side,
never client-side, and strips `actor_role`/`old_status`/`draft_version`/
`metadata` for customers even on rows they're allowed to see the rest of).

## 8. Confidence model, features and thresholds (Phases 7–8)

**Features** (`ai/models/confidence_model.py:FEATURE_SCHEMA`):
`classification_probability`, `classification_margin`, `retrieval_similarity`,
`retrieval_score_gap`, `citation_coverage`, `valid_evidence_count`,
`ocr_quality`, `description_completeness`, `draft_validation`. Built by
`app/services/confidence_gate.py:build_confidence_features` at ticket-creation
time and stored in `tickets.confidence_features`, so later Accept/Edit/Reject/
Escalate outcomes can be joined back to the exact feature snapshot for
retraining.

**Model**: scikit-learn `Pipeline(SimpleImputer → StandardScaler →
LogisticRegression(class_weight="balanced"))`, trained by
`ai/models/train_confidence.py` from real `feedback` + `tickets` rows (refuses
to train below 30 usable labelled outcomes — see §11 for what that means for
this repo's current state). Falls back to a fixed, documented linear
combination (`fallback_confidence`) whenever no trained artifact is active —
this is a labelled, not a hidden, degradation (`model_version ==
"safe-fallback-v1"`, `trained == False` in every response that used it).

**Registry / controlled retraining** (`ai/models/confidence_registry.py`,
Phase 13): a trained candidate is written to
`ai/models/artifacts/confidence_versions/{version}.joblib` and never becomes
live on its own. `python ai/models/train_confidence.py --deploy` promotes it
only if its ROC-AUC is ≥ the currently active version's (or `--force` to
override); `--rollback` restores the previous active version instantly.
`predict_confidence()` resolves the currently promoted version at call time —
promoting/rolling back takes effect without a redeploy.

**Department thresholds** (Phase 8): `GET/POST
/api/admin/departments/{id}/confidence-policy`, versioned, validated
(`low <= high`, both in `[0,1]`), every change audited
(`department.confidence_policy_updated`). No department policy → the global
defaults (`low=0.55`, `high=0.80`) apply. The gate itself: `score >= high` →
continue to evidence retrieval/drafting; `score < low` → route straight to
human investigation (`review_required=True`); between the two → the
department's configured borderline policy (currently: also routes to review,
the conservative default).

## 9. Retrieval sources and isolation (Phase 9)

Two sources, queried and ranked together, both scoped by an identical
`tenant_id + department_id` filter before ranking (`ai/graph/nodes.py:retrieve_node`):

1. **Knowledge base** (`embeddings` → `knowledge_base`): `status='approved'`,
   `is_publishable=true`, matching `article_version`, non-empty content.
   Citation id `KB-###`.
2. **Approved historical resolutions** (`ticket_resolution_embeddings`):
   `reusable=true`, non-empty text, excludes the ticket's own prior
   resolution. Only ever populated from a reviewer-approved `final_response`
   (`ai/embeddings/resolution_index.py`, called from `approve_draft()`; a
   best-effort operation that never fails ticket approval). Citation id
   `RT-###`.

`backend/tests/test_resolution_retrieval_isolation.py` proves, with two real
tenants and two real departments, that: a tenant only ever retrieves its own
resolutions; a department with no matching resolution retrieves none; and
citation-id prefixes never collide across sources.

## 10. Analytics metric definitions (Phase 12)

All computed server-side in `GET /api/analytics` — never client-only:

- `ai_acceptance_rate` = `feedback.action='accept'` rows ÷ all decided rows.
- `reviewer_modification_rate` / `engineer_edit_rate` = `action='edit'` rows ÷
  all decided rows (both draw from the same `edit` action — an engineer's
  saved edit and a reviewer's Modify & Approve are currently the same
  labelled outcome; see §11).
- `rejection_rate`, `escalation_rate` = `action='reject'`/`'escalate'` rows ÷
  all decided rows.
- `ai_human_agreement` = `action='accept'` rows ÷ all decided rows (how often
  the reviewer approved without any change).
- `confidence_distribution` = ticket counts bucketed at the same
  low(0.55)/high(0.80) thresholds the workflow gate uses.
- `average_response_time_hours` / `average_resolution_time_hours` = mean of
  `assigned_at - created_at` / `resolved_at - created_at`, in hours, over
  tickets that reached that milestone.
- `department_performance` = per-department ticket totals, resolved count,
  and average confidence.
- `pipeline_stage_latency` = mean `duration_ms`, sample count and failure
  count per instrumented stage (`pipeline_metrics`, §12).

## 11. OCR and text-correction evaluation (Phase 10)

```bash
# From the repo root, inside the api container or a matching local env:
python ai/evaluation/ocr_eval.py --dataset path/to/labels.jsonl --engines tesseract
python ai/evaluation/ocr_eval.py --dataset path/to/labels.jsonl --engines tesseract,easyocr,paddleocr,trocr

python ai/evaluation/text_correction_eval.py --dataset path/to/pairs.jsonl --methods rule_based,hybrid
python ai/evaluation/text_correction_eval.py --dataset path/to/pairs.jsonl --methods rule_based,symspell,transformer,hybrid
```

Dataset formats are documented in each script's module docstring. Both CLIs
**refuse to print a comparison table without a real `--dataset`** — see
`backend/tests/test_text_correction.py::test_evaluation_cli_refuses_to_fabricate_results_without_a_dataset`.
EasyOCR/PaddleOCR/TrOCR/SymSpell/transformer-correction are optional imports;
an engine/method reports `"available": false` with the pip install command if
its package isn't present, rather than failing the whole run.

**No labelled OCR or corrupted-text-correction dataset ships with this repo.**
This implementation status is Planned/Blocked for the actual comparative
numbers (see the top-level report's "Requires external credentials or
datasets" section) — the harness and its metric math are Implemented and
Verified (`backend/tests/test_evaluation_metrics.py`,
`test_text_correction.py`), but no real-world CER/WER/latency comparison
across OCR engines or correction methods has been run, and none is claimed.

## 12. Pipeline latency instrumentation (Phase 12)

`app/services/pipeline_metrics.py:stage_timer`/`persist_stage_timings` wrap:
`classification`, `routing`, `confidence_scoring`, `total_intake_pipeline`
(all in `POST /api/tickets`), `ocr_extraction` (attachment processing), and
`evidence_retrieval_and_drafting` (the combined LangGraph retrieve+draft+
validate invocation — not yet split into three separate stages; see
Limitations). Every row is best-effort: a metrics-write failure never fails
the request that produced it, and no ticket subject/description text is ever
stored in a metric row.

## 13. Configurable LLM provider (Phase 14)

`ai/agents/llm_interface.py:OpenAICompatibleProvider` — any OpenAI-compatible
chat-completions endpoint (OpenAI, Azure, or a self-hosted/local server).
Configuration is entirely environment-variable driven (`LLM_PROVIDER`,
`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`,
`LLM_MAX_RETRIES` — see `.env.example`); no key is ever hardcoded, and
instantiation fails closed (`RuntimeError`) if `LLM_API_KEY` is missing when
this provider is explicitly selected. Retries with exponential backoff on
timeout/5xx/429 (respecting `Retry-After` when present); a non-429 4xx fails
immediately, no retry. Malformed or non-JSON model output becomes a
structured `DraftGenerationResult(error=...)`, never an unhandled exception.
The deterministic provider remains the default and is unaffected — the
application works fully with no LLM key configured, for both drafting and the
description assistant (which additionally falls back to the deterministic
provider at the router level if a configured real provider raises for any
reason).

## 14. Environment variables (new in this pass)

| Variable | Default | Purpose |
|---|---|---|
| `VITE_SYNC_POLL_INTERVAL_MS` | `15000` | Frontend cross-role polling interval |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint base |
| `LLM_MODEL` | `gpt-4o-mini` | Model name sent to the configured provider |
| `LLM_MAX_RETRIES` | `2` | Retry budget for transient LLM errors |

`LLM_PROVIDER`, `LLM_API_KEY`, `LLM_TIMEOUT_SECONDS` already existed; see
`.env.example` for the complete, current list with descriptions.

## 15. Docker

No change to the one-command flow: `copy .env.example .env && docker compose
up --build`. `frontend/Dockerfile` gained two build args
(`VITE_SYNC_POLL_INTERVAL_MS`, mirrored in `docker-compose.yml`) with safe
defaults — omitting them changes nothing. Verified in this pass: a clean
`docker compose build api` from the Dockerfile (no layer/dependency changes
needed), `alembic upgrade head` reaching `0015`, `/api/health/ready` healthy,
the web container serving `200` on `/`, the full backend suite (95 tests)
green against the freshly built image, and a live HTTP smoke run of the
complete customer → engineer → reviewer → customer workflow against the
running container (§ of the top-level report has the transcript).

## 16. Testing commands

```bash
# Backend (run inside the api container, or locally with `uv sync --extra dev,rag`)
docker compose exec api pytest -q

# One new-feature slice at a time, if useful while iterating:
docker compose exec api pytest -q tests/test_synchronized_workflow.py tests/test_operations_api.py \
  tests/test_resolution_retrieval_isolation.py tests/test_confidence_registry.py \
  tests/test_llm_provider.py tests/test_analytics_pipeline_metrics.py \
  tests/test_evaluation_metrics.py tests/test_text_correction.py

# Frontend
cd frontend
npm run typecheck   # tsc -b --pretty false
npm test            # vitest run
npm run build        # tsc -b && vite build
```

## 17. Known limitations

- **Confidence model is running on the safe fallback in this environment** —
  fewer than 30 labelled outcomes currently exist, so `train_confidence.py`
  correctly refuses to train (by design; this is not a bug). The gate,
  registry, promotion and rollback machinery are all implemented and tested
  against synthetic candidates, but no real trained model has been promoted.
- **No labelled OCR or text-correction dataset ships with the repo** — the
  evaluation CLIs and their metrics are real and tested; no comparative
  accuracy numbers exist to report (see §11).
- **`evidence_retrieval_and_drafting` is one combined pipeline-latency stage**,
  not three separate `retrieval`/`drafting`/`citation_validation` rows —
  splitting it further would mean threading timing state through the
  LangGraph node graph itself, deferred as a follow-up.
- **`engineer_edit_rate` and `reviewer_modification_rate` currently share the
  same underlying `feedback.action='edit'` label** — the schema doesn't yet
  distinguish "an engineer edited their own draft" from "a reviewer used
  Modify & Approve" as separate outcome categories; the analytics endpoint
  reports the same figure for both today, which is honestly labelled but not
  a genuinely independent pair of numbers.
- **No WebSocket/SSE transport** — synchronization is polling-based by
  design (see §5); this is a deliberate, documented choice given the existing
  architecture, not a stopgap for a broken push mechanism.
- **True OCR-error correction is not yet wired into the live attachment
  pipeline** — `sanitized_text` (PII-redacted, not spelling-corrected) is what
  downstream classification/retrieval/drafting/confidence-scoring consumes
  today; the hybrid corrector built in Phase 10 is available as a library and
  evaluation target but isn't yet called from `attachment_extraction.py`.

## 18. Rollback instructions

- **Database**: `alembic downgrade 0010` reverts all five migrations added in
  this pass, in one step (each intermediate `downgrade()` is also independently
  correct if you need a partial rollback — see each file). This drops the new
  tables/columns; it does not attempt to resurrect data that only existed in
  them (e.g. draft version history).
- **Confidence model**: `python ai/models/train_confidence.py --rollback`
  reverts the active pointer to the previously promoted version without
  retraining anything; safe to run at any time, including with nothing
  currently promoted (reports "No previous version to roll back to").
- **Application code**: every change in this pass is additive to existing
  files or new files; reverting the corresponding commits removes it cleanly
  without touching unrelated Phase-1 functionality, since no existing route,
  model field, or component was removed or renamed.

## 19. Advanced-platform Release A audit

| Feature | Audit state | Evidence | Remaining action |
|---|---|---|---|
| Approved customer response | Implemented and verified | `services/workflow.py`, customer ticket API/UI tests | None |
| Engineer-reviewer workflow | Implemented and verified | `routers/workflow.py`, synchronized workflow tests | None |
| Immutable response versions | Implemented and verified | `response_drafts`, migrations 0011-0013 | None |
| Response comparison | Implemented; frontend verified | `GET /api/tickets/{id}/draft-comparison`, `TicketWorkspace.tsx` | Re-run container API test after Docker Desktop starts |
| Cross-login synchronization | Implemented and verified | configurable authoritative polling and reconnect state | Optional future WebSocket/SSE transport |
| Specialist assignment | Implemented and verified | tenant/department/capacity/specialization filters and row locking | None |
| Public/internal timelines | Implemented and verified | scoped paginated timeline endpoint | None |
| Team Lead workload dashboard | Implemented and verified | backend workload query and role dashboard | SLA-policy counts belong to Release D |

The response-comparison endpoint accepts optional `from_version` and
`to_version` parameters, rejects reversed version order, enforces the same
tenant/department ticket visibility as the rest of the workspace, and requires
the internal-AI permission. Its output is derived from immutable stored text:
word additions/removals, changed spans, edit percentage, and citation changes.
Customers cannot call it or see the comparison UI.
