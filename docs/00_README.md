# Documentation Index

This package defines a production redesign of an earlier MVP form/scheduling backend into a multi-tenant industrial operations platform.

## Product thesis
The platform replaces fragmented Excel-driven operational reporting with structured, governed, automated workflows while preserving Excel import/export for adoption. It combines workspace/project administration, dynamic forms, schedules, task inboxes, approval workflows, automation, master data, reporting, audit, integrations, and installable Domain Packs.

## Architectural thesis
- Core is industry-neutral.
- Domain Packs add industry/company semantics without forking Core.
- Production target is a modular monolith with clean module boundaries and event-driven internal workflows.
- PostgreSQL is the default system of record; JSONB is used where controlled schema flexibility is necessary.
- Object storage holds files; Redis/queue infrastructure supports background jobs.
- APIs are contract-first and versioned.

## Key documents
- Product: 01–04
- Domain: 05–16
- Architecture: 17–23
- Delivery: 24–28
- ADRs: `adr/`
- Domain Pack reference: `domain-packs/`

## Terminology
Tenant/Organization: commercial/customer boundary.
Workspace: collaboration/governance boundary inside an organization.
Project: operational execution boundary inside a workspace.
Department: organizational group that may receive scoped access to projects.
Domain Pack: installable package of forms, master data, workflows, automations, reports, mappings, and policy presets.
