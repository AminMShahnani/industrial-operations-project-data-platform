# ADR-0025: Controlled project tags and flags

Date: 2026-10-10
Status: Accepted implementation decision under the authorized next Phase 6 slice

## Context

docs/12 requires append tag/flag actions. docs/03 FR-016/051 permits controlled
project metadata; ADR-0011 establishes fresh delegated authority and owning-service
boundaries. Tags/flags have no specified governance semantics or target contract.
The existing action contains kind/value, with no target override. Implement this
vertical slice as project-owned descriptive annotations, using the rule's exact
project scope and existing project.manage/read policies.

## Decision

The projects application service owns a typed append-only annotation set. Tag and
flag are distinct kinds; values preserve case and the existing bounded ASCII action
contract. Labels never grant access, transition lifecycle, approve records, change
form data or run executable code. Industry meanings belong in Domain Packs.
Workspace-only rules fail explicitly rather than guessing a source/child project.
Targets on tasks, submissions, workflows and master data are not implicitly added.

Every execution requires the original activator's current organization/scoped
automation authority and current project.manage permission. Terminal projects refuse
writes, including duplicate requests. Project.read exposes paged annotations under
current tenant/workspace/project access, including authorized historical inspection.
There is no separate weaker annotation grant or public manual write endpoint.

One immutable row exists per organization/project/kind/exact value. Repeating an
append returns the first row, preserving its original author, timestamp and audit.
Each run/action still retains its own receipt, pointing to that row. A new append
records an immutable project audit in the same transaction and keeps existing
delegated run/version/event/correlation evidence. Project identity, description,
version and lifecycle are independent of annotations and remain unchanged.

Lock the project through its owning repository before checking duplicates and a
1000-annotation per-project bound. List/filter before a 100-row UUIDv7 cursor page;
reject foreign, missing or mismatched-filter cursors. UI scope changes discard old
rows and late responses. Show tags and flags with retained authorship/time metadata;
refresh after automation without exposing private event payloads.

## Persistence and rollback

Add a relational project_annotations table with composite project/user/audit foreign
keys, exact-value uniqueness, kind/value constraints and scoped cursor index. Bind
inserts to a matching immutable audit event; reject update/delete/truncate. No
existing project, submission or audit row is rewritten.
The audit tenant/ID uniqueness constraint supports the composite foreign key;
it does not change existing audit identities or content. Downgrade serializes writes
and refuses before DDL if annotations exist. Use verified backup/restore when
populated rollback is required; never erase evidence to force downgrade.

## Verification

Require scope/permission/revocation and terminal-project tests; duplicate/concurrent
appends, exact tag/flag distinction, bounded filtered pages/cursors, immutable audit
binding, atomic action failure/retry and populated rollback tests. Real browser and
committed Redis/concurrent execution verify the vertical slice. All local and exact
code hosted gates remain required; Phase 6 stays open for remaining work.
