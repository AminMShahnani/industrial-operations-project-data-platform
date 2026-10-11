# ADR-0034: Private report export job lifecycle

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 7 requires large report exports to run durably and to recheck access at
generation and download. Saved report definitions and dashboards are creator
private under ADR-0029 and ADR-0030. Report definitions have immutable versions;
operational rows continue to reflect current state.

## Decision

An export job is private to the report creator and binds to the exact saved-report
version, format, organization, workspace, project and request parameters at enqueue.
The worker uses the pinned definition to read current authorized data. Authorization
is rechecked before generation and at every download request. Artifacts remain in
private object storage for 24 hours, after which they are unavailable and eligible
for cleanup. Idempotent repeated delivery of a job cannot create multiple outputs
or repeat a completed export. A completed job can be downloaded only through an
authenticated API route; no persistent public or signed URL is stored.

PDF is a deterministic, text-only rendition of the selected report columns/groups,
with bounded rows and no user HTML, scripts or external resources.

## Consequences

- A definition edit does not change an already queued job's columns, filters or
  grouping, but the data reflects the worker's authorized execution time.
- Permission revocation before generation prevents output; revocation before
  download prevents artifact access.
- Artifacts expire after 24 hours. Storage cleanup is idempotent and may be retried.
- Import apply remains bounded and synchronous; large durable transfer jobs are
  deferred because the existing import contract is capped at 1,000 records and
  performs owning-service validation/audit in one transaction.
