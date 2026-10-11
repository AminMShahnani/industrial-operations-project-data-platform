# ADR-0028: Authorization for aggregate operational reports

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 7 reporting includes datasets that can return operational rows assigned to
other members. `task.read` grants personal task access and must not implicitly
grant cross-user reporting. The project owner was asked to choose the authorization
boundary for these aggregate reports.

## Decision

Aggregate task reports require the existing `schedule.manage` permission at the
selected workspace or project scope. Personal reports continue to use the owning
Tasks service's `task.read` and personal-assignment checks. Report projections omit
recipient IDs, claimant IDs, and submission IDs; this ADR does not grant access to
those identities or records. Every query continues through the Tasks application
service, which checks current membership, selected scope and permission.

The project owner selected this rule on 2026-10-11. No new Core permission or
industry-specific behavior is introduced.

## Consequences

- Workspace/project managers with `schedule.manage` may query aggregate task rows.
- Personal task readers cannot use aggregate scope; the server returns the normal
  authorization error.
- Filters and cursors remain bounded by the existing Tasks query contract.
- Shared saved-report definition visibility is a separate decision and remains
  private by default until resolved; see the Phase 7 open question.

## Alternatives considered

- Introduce `report.read` and add new role/scope grants. Rejected because the existing
  scoped `schedule.manage` capability already governs project-wide task inspection.
- Reuse `task.read` for aggregate rows. Rejected because it broadens personal access
  across members without an explicit authority grant.
