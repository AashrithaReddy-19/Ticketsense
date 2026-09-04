# TicketSense Release B — Explainable AI Pipeline

## Audit matrix

| Capability | Before Release B | Release B status | Evidence |
|---|---|---|---|
| LangGraph stages | Five combined stages | Implemented: 12 explicit typed stages | `ai/graph/__init__.py` |
| Persistent execution trace | Aggregate `pipeline_metrics` only | Implemented | `pipeline_executions`, `pipeline_stages` |
| Technical entities | Evaluation-only token helpers | Implemented deterministic extraction and audited correction API | `technical_entities.py`, `release_b.py` |
| Citation validation | Scope/ID/version checks | Expanded with coverage and unsupported-claim counts | `validate_citations_node` |
| Grounding validation | Citation warnings only | Implemented conservative claim checks and conflict/unsafe blocking | `grounding.py` |
| Confidence gate | Independent intake confidence | Reused inside graph; human review remains mandatory | `confidence_node`, `human_review_gate_node` |
| Explainability | Analysis summary only | Implemented staff-only actual-signal API/UI | `/explanation` |
| Pipeline UI | Derived snapshot stages | Implemented persisted stage display; legacy empty fallback retained | `TicketWorkspace.tsx` |

## Architecture

```text
START → intake → attachment/text → technical entities → classification
      → priority → routing → tenant/department-scoped retrieval → drafting
      → citation validation → grounding validation → independent confidence
      → human review gate → END
```

These are orchestration nodes. Deterministic nodes are not represented as trained
models. The existing classifier, Sentence Transformer, pgvector retrieval,
provider-neutral drafting and confidence artifact/fallback remain intact.

## Persistence

Migration `0016` adds append-oriented executions, stages, entities and claims.
Migration `0017` aligns UUID server defaults with the repository ORM mixin.
Trace metadata contains safe summaries and keys, never raw prompts, credentials,
or complete ticket descriptions.

## APIs and security

- `GET /api/tickets/{id}/pipeline-trace`
- `GET /api/tickets/{id}/technical-entities`
- `POST /api/tickets/{id}/technical-entities/{entity_id}/corrections`
- `GET /api/tickets/{id}/explanation`

Read endpoints require staff role plus the existing ticket visibility policy.
Support agents are assignment/department scoped, reviewers and Team Leads are
department scoped, System Admin is tenant scoped, and Auditor is read-only.
Customers receive `403`. Corrections require update/review permission and append a
new entity linked to the original plus an audit event.

## Extraction rules

Structured regex/rule extraction covers error codes, valid IPv4/IPv6 addresses,
URLs, paths, versions, common commands, operating systems, devices and affected
services. Exact raw values and character offsets are retained. Ordinary standalone
numbers are not treated as error codes. No heavyweight NER dependency was added.

## Validation and gating

Citation validation checks IDs against the retrieved set, tenant, department,
approval, publishability, content, and version; it records valid/invalid IDs,
coverage and uncited-claim count. Grounding splits draft text into citation-attached
claims and reports Supported, Partially Supported, Unsupported or Not Verifiable.
It blocks potentially destructive instructions and conservatively flags conflicting
approved evidence. This is decision support, not proof of factual correctness.

The graph consumes the already-independent confidence score. High confidence plus
grounded output follows normal controlled review; borderline/partial output carries
a mandatory warning; low, unsupported, conflicting or unsafe output requires human
investigation. Human approval is always required before customer publication.

## Known limitations

- Attachment extraction still runs through the existing attachment endpoint before
  graph execution; the graph consumes stored corrected/sanitized text rather than
  running heavyweight OCR itself.
- Deterministic lexical grounding can produce false positives/negatives and does not
  establish real-world truth. No external NLI provider is required or claimed.
- Candidate department probabilities appear only when the active classifier exposes
  them; otherwise the UI correctly shows “Not available”.
- Validation is persisted for generated AI drafts and claims. Independent validation
  of every later human-edited version remains a future hardening step.
- Release C evaluation and Release D incident/SLA/knowledge-gap features are outside
  this release.

## Verification commands

```powershell
docker compose up --build -d
docker compose exec -T api alembic current
docker compose exec -T api pytest -q tests/test_release_b_ai.py
docker compose exec -T api pytest -q tests/test_grounded_rag.py
Set-Location frontend
npm.cmd run lint
npm.cmd test -- --run
npm.cmd run build
```
