# TicketSense V2 — Final Report

This report covers the upgrade of the verified "TicketSense Enterprise
v1.0" release into TicketSense V2. Every number in this document was
either read directly from a real test run, a real live API call against
the real demo tenant, or a real database query — none are estimated or
invented. Where a real number doesn't exist yet (e.g. no evaluation runs
are currently registered on the demo tenant), that is stated as a fact,
not filled in with a plausible-looking placeholder.

## 1. Branch and commit history

- Base: git tag `ticketsense-enterprise-v1.0` (commit `4f61e56`) — **untouched** throughout this effort. No applied migration was rewritten, and the tag was never moved or deleted.
- Branch: `feature/ticketsense-v2-innovation`
- HEAD: `489c128`
- 18 commits on top of v1.0, one per phase plus one hygiene fix, in dependency order:

| Commit | Phase |
|---|---|
| `41bb7c9` | Phase 1 — governance foundation: feature flags, provider/model registry, capability bundles |
| `8aa20e5` | Phase 2 — leakage-safe dataset registry and ingestion |
| `19781dd` / `66b152e` | Phase 3 — Evaluation Lab (backend + admin UI) |
| `25b8ace` | Phase 4 — adaptive threshold simulation |
| `168204e` | Phase 5 — Resolution Passport |
| `5de17fc` | Phase 6 — counterfactual decision explanations |
| `8e1d115` | Phase 7 — tenant-isolated dependency graph / GraphRAG traversal |
| `eb7a579` | Phase 8 — shadow mode and champion/challenger experiments |
| `47def7d` | Phase 9 — adversarial AI safety / red-team lab |
| `35cd55d` | Phase 10 — knowledge-conflict detection |
| `1418a2d` | Phase 11 — OCR/multimodal diagnostic benchmark lab |
| `a743ec9` | Phase 12 — production-shaped external connector (Slack) |
| `42bf126` | Phase 13 — near-real-time ticket events (SSE) |
| `1233d60` | Phase 14 — process mining |
| `e7205a6` | Phase 15 — change-aware incident correlation |
| `961038d` | Phase 16 — production hardening (CI, dependency audit, SBOM, backup runbook, honest SSO status) |
| `489c128` | Fix — cleaned up a real test-data leak into the global feature-flag catalog (see §8) |

Total diff vs. v1.0: **146 files changed, +26,995 / −32 lines**.

## 2. Database migrations

- v1.0 Alembic head: `0025`
- V2 Alembic head: **`0038`** (13 new migrations, all additive — no destructive schema change, no column drops on existing tables, no data rewrites of pre-existing rows)
- Every new migration's `upgrade()`/`downgrade()` pair was actually run in an up → down → up cycle during this effort, not just written and assumed correct.

## 3. Test totals

| | v1.0 baseline | V2 final | Verified |
|---|---|---|---|
| Backend (pytest) | 166 / 166 | **284 / 284** | Full suite re-run after every phase, and once more after the final hygiene fix |
| Frontend (vitest) | 59 / 59 | **91 / 91** | Full suite re-run after every phase |

118 new backend tests and 32 new frontend tests were added across the 16 phases — none by weakening or skipping an existing assertion. The frontend production build (`vite build`) was re-verified clean after every phase that touched frontend code.

## 4. What's completed vs. feature-flagged

All 14 feature flags reserved in migration `0026` back when the governance foundation was built are now **fully implemented** — none remain a pure stub:

| Flag | Owner | Status |
|---|---|---|
| `evaluation_lab` | AI Governance | Implemented — real classifier evaluation runs, leakage-safe dataset registry |
| `resolution_passport` | Support Platform | Implemented — immutable, hash-verified audit record on every resolution |
| `counterfactual_explanations` | AI Governance | Implemented — deterministic, gate-based explanations, never fabricated reasoning |
| `graphrag` | Knowledge Platform | Implemented — tenant-isolated dependency graph with live re-authorization per hop |
| `shadow_mode` | MLOps | Implemented — non-mutating candidate inference sampling |
| `challenger_models` | MLOps | Implemented — champion/challenger lifecycle, real second trained model |
| `red_team_lab` | Security | Implemented — 9 adversarial cases against real defenses, 1 known honest gap |
| `multimodal_analysis` | AI Platform | Implemented — pluggable OCR benchmark lab (real CER/WER) |
| `change_correlation` | Operations | Implemented — real change-vs-incident temporal correlation |
| `real_time_events` | Platform | Implemented — SSE accelerant, polling never disabled |
| `external_connectors` | Integrations | Implemented — real Slack webhook connector, allowlisted host |
| `adaptive_thresholds` | AI Governance | Implemented — historical-data threshold simulation, never auto-applied |
| `knowledge_conflict_detection` | Knowledge Platform | Implemented — real conflict detection, blocks auto-resolution on open high-severity conflicts |
| `process_mining` | Operations | Implemented — real variant/bottleneck analysis over the immutable event log |

"Implemented" means real, tested, working code behind the flag — it does **not** mean every flag is turned on in the real demo tenant today (see §6 for the current, honest, mostly-off state of the live demo tenant).

## 5. Security and adversarial results

**Red-team lab** (real run against the live demo tenant, this session):
- 9 total cases, 8 applicable to this tenant's configuration, 1 not applicable
- **Block rate: 87.5%** (7 of 8 applicable defenses held)
- **Attack success rate: 12.5%** (1 of 8)
- The one honest gap: `encoded_secret_redaction_gap` (medium severity) — the PII/secret redactor's regex-based detection does not catch a base64-encoded secret. This is a real, currently-unfixed gap, deliberately left in the suite and this report rather than silently patched and re-reported as 100% — the redactor is regex/pattern-based, not a semantic decoder, and closing this gap requires either a base64-scanning heuristic (with its own false-positive risk) or a different redaction approach; that tradeoff was not resolved in this effort.

**Dependency vulnerability scanning** (real scans, this session):
- `pip-audit` across every backend runtime dependency: **0 known vulnerabilities**.
- `npm audit`: found and fixed a real set of high/critical-severity `react-router` advisories by bumping `react-router-dom` 7.9.1 → 7.18.3 (zero test/build regressions, identical production bundle hash). One moderate finding remains, deliberately deferred (Vite/esbuild dev-server-only advisory requiring a breaking major-version upgrade) — see `docs/sbom/README.md`.

**Tenant isolation**: every new table added this effort carries a `tenant_id` foreign key to `organizations` with `ON DELETE CASCADE`, and every new query filters by the authenticated user's `tenant_id`. The GraphRAG traversal (Phase 7) additionally re-verifies authorization live at every hop rather than trusting cached node attributes, and hard-caps customer-role traversal to depth 1. The SSE event stream (Phase 13) independently re-checks per-event visibility before relaying anything, proven by a test against another customer's ticket in the same tenant.

## 6. The live demo tenant's honest current state

A real, live verification pass was run against the demo tenant as part of writing this report (not from memory or an earlier phase):

- **OCR engines**: Tesseract, EasyOCR and PaddleOCR are all honestly reported `available: false` in this environment — Tesseract's binary and both optional Python packages are genuinely not installed here (Tesseract is only installed inside the production Docker image). No fabricated score was ever produced.
- **External connectors**: all 7 catalogued providers (`email`, `github`, `jira`, `microsoft_teams`, `servicenow`, `slack`, `webhook`) report `status: "not_configured"`. The Slack connector's real code path was exercised and correctly failed closed with "Environment variable ... is not set" rather than reporting success.
- **SSO**: `{"oidc": {"configured": false}, "saml": {"configured": false}}` — no IdP credentials exist anywhere in this repository.
- **Evaluation Lab**: 0 datasets currently registered on the demo tenant. The lab is fully functional (verified with scratch datasets during Phase 3 and never left registered on the demo tenant) — an operator needs to register a real dataset before it shows anything.
- **Champion/challenger comparison**: `"data_sufficient": false, "reason": "No shadow runs have been recorded for this task yet."` — again, the mechanism works (verified with scratch data in Phase 8) but has not been exercised against live demo traffic.
- **Process mining** (real run against real demo ticket history, this session): 7 tickets with recorded events, 36 total events, real variants (e.g. one ticket followed `ticket_routed → ticket_submitted → ai_processing_started → ticket_classified → ticket_assigned`) and real bottleneck timings (e.g. `ai_processing_started → work_started` averaged ~105 seconds in this small sample).
- **Knowledge conflicts**: a real scan against the demo tenant's actual knowledge base found 7 real contradictory-steps conflicts among genuine demo KB articles (consistent with the finding first made in Phase 10) — reviewed and left for an Admin to act on, not auto-resolved.

## 7. Performance and cost — stated honestly

**No real LLM cost has ever been incurred anywhere in this effort.** This deployment's `LLM_PROVIDER` is `stub` (the `DeterministicDevelopmentProvider`) — the same as it was in v1.0. A real query of `ai_usage_events` (74 real logged rows) confirms this directly: every row's provider is either `deterministic-development` (100% success, ~353ms average latency — internal template generation time, not LLM inference latency) or `pipeline_unavailable` (a fallback path). `estimated_cost_usd` is `NULL`/zero for all of them. This was a pre-existing v1.0 limitation, not something V2 fixed — a real deployment must set `LLM_PROVIDER=openai_compatible` with a real API key before any of the cost/latency tracking infrastructure (already wired, unchanged from v1.0) reports a genuine number.

## 8. Data safety — what was and wasn't touched

- The v1.0 git tag was never moved, deleted, or force-pushed over.
- Every new migration is additive (`CREATE TABLE`, `ALTER TABLE ... ADD COLUMN`) — no existing table was dropped, no existing column's data was rewritten.
- One real data-hygiene bug was found and fixed during this report's own verification pass: `test_change_correlation.py` (Phase 15) created global `FeatureFlag` catalog rows for its test fixtures but never cleaned them up, leaking 6 `test-flag-*` rows into the real, shared feature-flag governance list visible to every tenant's Admins. This was caught by this report's own live data-gathering pass, not by the test suite itself — a reminder that "tests pass" and "no residue in the shared database" are different guarantees. The 6 leaked rows were deleted, the test's teardown was fixed, and the full backend suite was re-verified (284/284) after the fix.
- A second, smaller leftover (one empty orphaned organization row from earlier work on Phase 13's test file, before a since-removed code path was cleaned up) was also found and deleted in the same pass.
- Final sweep, confirmed clean: exactly 1 organization (the real demo tenant), 0 leaked feature flags, 0 leftover OCR/process-mining/knowledge-conflict rows, 0 test-pattern user emails in the demo tenant's 143 real user accounts.
- No customer, ticket, or resolution data was deleted or exposed at any point in this effort.

## 9. Demo routes and accounts

New V2 admin pages (each gated by its own capability, visible only to roles with that permission):

- `/admin/ai-governance` — feature flags, provider/model lifecycle, shadow mode
- `/admin/evaluation-lab` — dataset registry and classification evaluation runs
- `/admin/red-team-lab` — adversarial safety suite
- `/admin/knowledge-conflicts` — contradictory-article detection and review
- `/admin/ocr-benchmark-lab` — OCR engine benchmarking
- `/admin/connectors` — external connector configuration and verification
- `/admin/process-mining` — variant discovery and bottleneck analysis

Existing pages extended in place: ticket workspace (resolution passport, counterfactual explanations, dependency graph tab), the Incidents page (root-cause hypothesis plus the new change-correlation panel), and the Tickets/ticket-workspace pages (low-latency SSE update nudge alongside unchanged polling).

Demo accounts (all password `Demo@123`, unchanged from v1.0):
- `customer@demo.com` — customer experience
- `agent@demo.com` — engineer/support-agent experience
- `sysadmin@demo.com` — full admin experience, needed to reach every `/admin/*` page above and to toggle feature-flag overrides for demoing a currently-off capability

## 10. Honest remaining limitations

- **CI is authored, not executed**: `.github/workflows/ci.yml` mirrors this session's real, manually-verified command sequence, but has not itself run on GitHub's Actions infrastructure in this effort.
- **No real LLM has ever been called** (see §7) — every AI draft in every demo and test is deterministic-template output.
- **Evaluation Lab and shadow/champion-challenger have no data on the live demo tenant** — both mechanisms are real and tested, but an operator must register a dataset / accumulate shadow-mode traffic before either shows a live result.
- **One real, unfixed security gap**: base64-encoded secrets are not caught by the redactor (§5).
- **One deferred dependency finding**: a moderate Vite/esbuild dev-server-only advisory, requiring a breaking toolchain upgrade not attempted this late in the effort.
- **OIDC/SAML has configuration-status detection only** — no token-exchange flow is implemented; building one without a real IdP to test against would have meant shipping unverified security-critical code, which was avoided on purpose.
- **OpenTelemetry-based distributed tracing was not implemented** in this effort — the existing (v1.0) `ai_usage_events`/`observability:read` mechanism remains the only observability surface. This is an explicit scope cut, not an oversight — the original plan called for OTel, and it is documented here as not done rather than silently dropped.
- **Accessibility was spot-checked, not formally audited** — no automated axe-core/Lighthouse pass was added this effort; existing accessibility affordances (skip link, `aria-live` toast region, labelled form fields) were preserved and extended, but a full WCAG audit was out of scope for this effort.
- **Backup/restore was rehearsed for the database only** (§ see `docs/OPERATIONS_BACKUP_RESTORE.md`) — a real `pg_dump`/`pg_restore` cycle was executed and its row counts verified, but cutting a running `api` container over to a restored database, and restoring the separate attachment-storage volume, were not rehearsed.
- **The in-process SSE event bus is single-process** — documented in code and here rather than silently assumed to work across a multi-replica deployment; a real horizontally-scaled deployment needs a shared broker (e.g. Redis pub/sub) in front of the same interface.

## 11. Reproducing these results

```bash
git clone <this repo> && cd ticketsense
git log --oneline ticketsense-enterprise-v1.0..feature/ticketsense-v2-innovation   # this report's 18 commits
cd backend && pip install ".[dev,rag]" && alembic upgrade head && python -m pytest -q   # 284 passed
cd ../frontend && npm ci && npm run typecheck && npm run test && npm run build          # 91 passed
```
