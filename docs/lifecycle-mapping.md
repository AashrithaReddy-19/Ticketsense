# Ticket lifecycle mapping

TicketSense keeps the deployed lifecycle values `open`, `in_review`, `resolved`,
`escalated`, and `closed`. Renaming them would invalidate existing persisted tickets,
queue filters, reviewer actions, API clients, UI badges, and audit interpretations.
The roadmap's `submitted`, `classified`, `routed`, and `drafted` values describe AI
processing milestones; they are recorded separately in `ticket_history`,
`analysis_status`, and `routing_state` rather than overloaded as durable ticket states.

| Roadmap milestone | Persisted representation |
|---|---|
| `submitted` | Ticket is created with `status = open`; `ticket_created` history event |
| `classified` | `ai_analysis_completed` history event and persisted classification fields |
| `routed` | `routing_state = routed` or `manual_triage`; `department_id` when resolved |
| `drafted` | `ai_draft_reply` plus `analysis_status = complete` |
| `reviewed` | `status = resolved` after approval/edit, or `in_review`/`escalated` when more work is required; immutable `human_reviews` row |
| `closed` | `status = closed` after the customer-facing lifecycle is complete |

## Allowed operational transitions

```text
open -> in_review | escalated | resolved
in_review -> resolved | escalated
escalated -> in_review | resolved
resolved -> open | closed
closed -> open
```

The API must reject unsupported actions and must never infer authorization from a
requested transition. Visibility and role checks run before transition handling.
