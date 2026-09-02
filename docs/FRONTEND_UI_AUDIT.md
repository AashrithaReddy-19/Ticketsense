# TicketSense frontend UI audit

Audit date: 2026-09-01

## Existing application surface

The React application currently exposes authentication, role-aware dashboards, customer tickets, ticket creation and detail, support/reviewer/team-lead queues, knowledge, incidents, notifications, AI/report data views, audit logs, integrations, and protected placeholder administration/settings routes. The main shared components are the authenticated shell, state views, icons, status mappings, buttons, fields, file upload, cards, badges, tabs, dialogs/drawer, toast, breadcrumbs, pagination, search, filters, timeline, skeleton, evidence cards, and attachment cards.

## Problems found

- Earlier styles and newer design-system styles coexist, producing inconsistent spacing, controls, tables, and state presentation.
- Some visible copy contains mojibake from an earlier encoding conversion.
- Customer ticket detail previously omitted safe attachment metadata, final-response presentation, and lifecycle progress.
- Some modules were hidden from role navigation but were not protected at the route level.
- Queue pages depend heavily on wide row layouts and need responsive card behaviour at narrow widths.
- Several pages use generic record lists where semantic tables would be easier to scan.
- Loading and empty states exist, but mutation success is not consistently announced outside toasts.
- Breadcrumbs and dialog focus management are present; tab keyboard arrow navigation and popover dismissal still need strengthening.
- Existing admin APIs do not expose complete user/role/department CRUD, so unsupported controls must not be invented.

## Reuse decisions

Keep the current API client, authentication context, role permission checks, shell routing, centralized status mapping, SVG icon set, state components, form primitives, dialogs, toast provider, evidence cards, grounded-draft interaction, attachment panel, and workspace actions. Modernize pages incrementally around these primitives rather than replacing working integrations.

## Minimum safe redesign plan

1. Consolidate tokens and primitives, then stabilize the responsive application shell.
2. Modernize login, customer dashboard, ticket form, list, and customer-safe detail.
3. Modernize internal queues and TicketWorkspace while preserving every action, tab, citation, draft, and attachment state.
4. Improve reviewer, team-lead, auditor, and supported administrator views without fake metrics or controls.
5. Finish responsive/accessibility states, tests, and visual inspection using seeded role accounts.

Backend APIs, database schema, RBAC, ticket lifecycle, RAG, citations, embeddings, and OCR processing remain outside this UI redesign.
