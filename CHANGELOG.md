# Changelog

## Unreleased — Advanced platform Release A hardening

- Added a staff-only immutable response-version comparison API and responsive
  workspace interface with selectable versions, word-level changes, edit
  percentage, and citation-change counts.
- Added negative customer authorization coverage and deterministic assignment
  setup to the synchronized end-to-end workflow test.

## Unreleased — Release B explainable AI pipeline

- Formalized a 12-stage LangGraph while retaining existing classifier, RAG,
  provider and confidence implementations.
- Added persisted executions, stages, technical entities and claim validations via
  additive migrations `0016` and `0017`.
- Added staff-only pipeline trace, Technical Information and deterministic
  explainability APIs and workspace panels.
- Expanded citation coverage reporting and added conservative claim grounding,
  unsafe-instruction blocking and conflicting-evidence detection.

All notable changes to TicketSense are documented here. Dates are UTC. This project
has not yet cut a tagged release; version numbers below are recommendations for the
maintainer to apply at release time, not existing Git tags.

## [Unreleased] — controlled workflow, sync, retrieval and evaluation expansion

This entry covers the phase-ordered enhancement pass that took the existing
Phase-1 authentication/RBAC/ticket-visibility foundation to a complete,
independently-scored, human-reviewed response workflow with cross-role
synchronization, department-scoped retrieval over two evidence sources, a
controlled confidence-model retraining path, a configurable real LLM provider,
and expanded analytics, evaluation tooling and test coverage.

### Added

- **Customer-visible approved responses** (`tickets.final_response`,
  `final_response_draft_id`, `final_responder_id`, `final_approver_id`,
  `approved_at`, `resolved_at`, `public_status_message`): the exact
  reviewer-approved text, never a draft, is what customers see, persisted
  independently of the internal draft trail.
- **Cross-role synchronization**: configurable polling (`useAutoRefresh`,
  `VITE_SYNC_POLL_INTERVAL_MS`) re-fetches authoritative ticket/queue data
  through the same authorized endpoints every view already uses, with a visible
  live/syncing/reconnecting indicator, in-progress-edit protection, and no
  optimistic state.
- **Engineer specialization and automatic assignment**
  (`engineer_departments`, `engineer_specializations`, `users.is_available`,
  `max_active_workload`, `last_assigned_at`): least-active-workload selection
  with a specialization-match preference, row locking for concurrency safety,
  and a recorded selection reason. Manual reassignment by Team Lead/Admin is
  supported and never silently overwritten.
- **Full engineer → reviewer → customer workflow** (`response_drafts`,
  `ticket_events`, backend-enforced `ALLOWED_TRANSITIONS`): accept, start work,
  save/submit drafts, and reviewer approve / modify-and-approve / request
  changes / escalate, each a backend-validated state transition.
- **Immutable draft-version history and audit trail**: every draft is a new
  `response_drafts` row (never overwritten); `ticket_events` is an append-only,
  role-filtered timeline (customers see only public events).
- **Team Lead workload dashboard** (`GET /api/workloads/engineers`): backend-
  computed per-engineer active/in-progress/under-review/escalated/resolved
  counts, capacity percentage and average resolution time.
- **Independent confidence model** (`ai/models/confidence_model.py`,
  `ai/models/train_confidence.py`): a separate Logistic Regression model (never
  the drafting LLM's self-reported confidence), with a safe deterministic
  fallback when no trained artifact exists.
- **Controlled retraining workflow** (`ai/models/confidence_registry.py`):
  versioned candidate artifacts, comparison against the currently active
  model, an explicit `--deploy` gate, and `--rollback`.
- **Department-specific confidence thresholds**
  (`department_confidence_policies`, `/api/admin/departments/{id}/confidence-policy`):
  versioned, validated (`low <= high`, both in `[0,1]`), audited threshold
  configuration with a global default fallback.
- **Approved-historical-resolution retrieval** (`ticket_resolution_embeddings`):
  a second, tenant/department-scoped evidence source alongside the knowledge
  base, populated only from reviewer-approved `final_response` text, cited with
  a distinct `RT-###` id never colliding with `KB-###` knowledge-base citations.
- **OCR and text-correction evaluation tooling** (`ai/evaluation/`): real
  CER/WER/error-code-accuracy/technical-token-preservation metrics, a
  multi-engine OCR comparison CLI (Tesseract built in; EasyOCR/PaddleOCR/TrOCR
  optional), and a rule-based/SymSpell/transformer/hybrid text-correction
  comparison CLI. Both refuse to print fabricated results without a real
  labelled dataset.
- **AI-assisted description improvement** (`POST /api/tickets/assist-description`):
  suggest-only, customer must accept/edit/discard; falls back to a rule-based
  provider if a configured real LLM is unavailable.
- **Pipeline-stage latency instrumentation** (`pipeline_metrics`): real timing
  for classification, routing, confidence scoring, OCR extraction and the
  combined evidence-retrieval/drafting stage.
- **Expanded analytics** (`GET /api/analytics`): AI acceptance/edit/reviewer-
  modification/rejection/escalation rates, confidence distribution, department
  performance, average response/resolution time, and pipeline-stage latency,
  plus an analytics dashboard UI.
- **Configurable real LLM provider** (`OpenAICompatibleProvider`): timeout,
  retry-with-backoff, 429/Retry-After handling, fail-fast on other 4xx,
  structured-output validation, and provider/model recording. The deterministic
  provider remains the default and the app works fully without any key set.
- **Feedback text-change tracking** (`feedback.text_change_ratio`): the
  character-level edit distance between a reviewer's final text and the draft
  it replaced, recorded as a labelled-feedback feature for retraining.
- Frontend/backend test coverage for all of the above (see `README.md` →
  Development checks for exact commands).

### Fixed

- `system_admin` was missing the `department:manage` and `engineer:manage`
  permissions in the enforcement-side RBAC table (`backend/app/core/rbac.py`),
  even though migration `0011` had already granted them at the database level —
  admins could not configure department confidence thresholds. Now consistent.
- `GET /api/analytics` only accepted a fixed legacy role list
  (`manager`/`enterprise_admin`/`admin`/`ai_admin`/...), silently excluding the
  canonical `team_lead`, `system_admin` and `reviewer` roles. Extended
  additively; legacy roles remain accepted.
- The OpenAI-compatible provider's evidence-prompt builder indexed
  `retrieved_evidence[0]` unconditionally, raising `IndexError` whenever a
  draft was requested with zero retrieved evidence.
- The technical-token detector's `error_code` pattern overlapped with
  `ticket_id` (e.g. `TKT-9001` also matched the generic error-code regex),
  double-counting a token across two categories and, in the hybrid corrector,
  producing an unrestorable nested placeholder when a ticket ID appeared
  inside a URL. Patterns are now non-overlapping and ordered so a URL/path
  masks whole before its contents are considered separately.

### Migrations

`0011` synchronized response workflow (draft versions, ticket events, engineer
department/specialization tables) · `0012` workflow integrity constraints ·
`0013` assignment capacity, confidence policies, pipeline metrics · `0014`
approved-historical-resolution retrieval table · `0015` feedback
text-change-ratio column. All are additive/reversible; see each file's
`downgrade()` for the exact rollback.

### Recommended version

**v0.2.0** (pre-1.0, backward-compatible additive feature set on top of the
existing Phase-1 foundation). No tag has been created — this is a
recommendation for the maintainer, per the project's release process.
