# Week 6 — Evidence-grounded RAG drafting

## Flow

`START → classify → route → scoped pgvector retrieve → draft → validate citations → END`

Retrieval remains tenant-, department-, approval-, version-, and publishability-scoped.
Retrieved passages receive stable request-local labels (`KB-001`, `KB-002`, …), while
database IDs remain in the internal evidence snapshot for validation.

## Provider configuration

`LLM_PROVIDER=stub` (also `deterministic` or `development`) selects the explicitly
labelled deterministic development provider. It performs no network request and copies
only supplied evidence passages into a human-review draft. Unknown provider names fail
closed. `LLM_API_KEY` is reserved for a future provider adapter; no key is required by
the development provider or tests.

The provider returns Pydantic-validated structured content: draft text, citations, and
an insufficient-evidence flag. It must not invent commands, URLs, policy, people,
timelines, error meanings, or resolution claims. Empty evidence produces a safe
insufficient-evidence response.

## Persistence and API

Migration `0009` adds one idempotently updated `ai_drafts` snapshot per ticket. It stores
the draft, citation/evidence references, provider metadata, generation/validation state,
safe diagnostics, and attempt count.

- `POST /api/tickets/{id}/ai-draft/generate` — authorized department engineer/reviewer
- `GET /api/tickets/{id}/ai-draft` — internal AI roles within existing ticket visibility

Customers cannot access either internal endpoint. Cross-tenant and cross-department
ticket IDs return the existing scoped not-found response. Auditors cannot regenerate.
Only citation-valid drafts are copied to the ticket's reviewable draft field.

## Validation

The deterministic validator rejects unknown IDs, cross-tenant/department evidence,
wrong versions, unapproved/unpublishable/empty evidence, structured citations missing
from the text, and technical drafts with no citation. Insufficient-evidence responses
may contain no citation.

**This stage performs deterministic citation and evidence validation. It does not
guarantee complete hallucination detection.**

## Reliability

`classify_node` and `retrieve_node` run the sklearn classifiers and the sentence-transformers
encode call through `asyncio.to_thread`, since both are synchronous CPU/IO-bound calls that
would otherwise block the single-process async event loop for the whole API — including
unrelated health checks — for as long as classification/embedding takes (worst case, a
first-run model download). Draft persistence uses an atomic `INSERT ... ON CONFLICT
(ticket_id) DO UPDATE` rather than a select-then-insert, so two concurrent generate requests
for the same ticket (e.g. a client retry after a slow response) update the same row instead
of racing on the `uq_ai_drafts_ticket` constraint.

## Embedding-model cache

`docker-compose.yml` mounts a named volume (`hf_cache`) at `/root/.cache/huggingface` on the
`api` service. Without it, every fresh container had to re-download
`sentence-transformers/all-MiniLM-L6-v2` (~88 MB) from the Hugging Face Hub on its first
retrieval/classification request — this is what produced the multi-minute first-draft
timeout. With the volume, the download happens once per host and survives container
recreation (`docker compose up`, `restart`, image rebuilds); a fresh clone or a different
host still pays the one-time download.

Setup is automatic — no manual step is required beyond `docker compose up -d`, since Compose
creates the named volume on first use. To pre-warm it deliberately (e.g. before a demo, to
avoid the ~90 s first-request cost): `docker compose up -d db api` and issue one ticket +
`POST /api/tickets/{id}/ai-draft/generate` call before the audience arrives.

Measured load tiers (this environment, cold container, network path unrestricted):

| Path | Typical duration |
|---|---|
| First request ever (network download + import + encode) | ~90 s |
| First request per process after a restart, cache warm on disk (import + disk load + encode) | ~15–20 s |
| Every subsequent request in the same process (in-memory singleton) | <0.3 s |

`classify_node`/`retrieve_node` bound the whole load-plus-inference call with
`MODEL_LOAD_TIMEOUT_SECONDS` (default 120s, see `.env.example`) via `asyncio.wait_for`, so an
unreachable Hub or a truly stuck download fails the request with a clear
`generation_status: "failed"` / `generation_error: "TimeoutError"` instead of hanging it
indefinitely — consistent with `draft_node`'s existing `LLM_TIMEOUT_SECONDS` bound. This never
falls back to token-overlap retrieval; a model-load failure is a failed generation, not a
silent scope change.

## scikit-learn version consistency

`ai/models/artifacts/*.joblib` is gitignored ("regenerate via `ai/models/train_classifier.py`")
and the API image already supports fresh-container training (`test -f
department_classifier.joblib || python train_classifier.py` in `backend/Dockerfile`). A stale
artifact set trained under scikit-learn 1.6.1 had been carried in the local build context from
an earlier session, while `pyproject.toml` pins only a floor (`scikit-learn>=1.5`), which
resolved to 1.9.0 in the image — producing `InconsistentVersionWarning` on every classifier
load. Rather than pin the runtime backward (fighting the floor-pinned, regularly-updated
dependency spec, and re-creating the same mismatch on the next PyPI release), the artifacts
were regenerated with the current runtime (`ai/models/train_classifier.py`, deterministic via
`random_state=42`) and now load with zero warnings. If a future rebuild's scikit-learn version
moves again, the same regeneration step keeps them in sync — this is the repository's intended
fresh-container design, not a one-off patch.

## Run and demo

```powershell
docker compose up --build -d
docker compose exec api alembic current
docker compose exec api pytest -q
Set-Location frontend
npm.cmd test -- --run
npm.cmd run build
```

For a demo, open an engineer-visible Networking ticket, select **Generate draft**, then
select an inline `[KB-...]` citation to locate its evidence card. Test an unrelated query
to demonstrate the insufficient-evidence state. Drafts persist in PostgreSQL across API
restarts.

## Known limitations

- No external LLM adapter is included yet; the development provider is deliberately not
  presented as an LLM.
- Stable labels are stable within a retrieval snapshot, not global article identifiers.
- Validation proves citation/scope consistency, not semantic entailment of every claim.
- Confidence scoring and human accept/edit/reject gating remain deferred to Weeks 8–9.
- The embedding-model cache volume is per-Docker-host; a genuinely offline host still needs
  one successful network fetch before the first draft, or the model baked into the image.
- Priority/sentiment classifier accuracy is low on the ~100-row synthetic training set by
  design (see `ai/models/train_classifier.py`'s docstring) — it proves the pipeline
  end-to-end, it is not a tuned model.
