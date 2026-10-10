# ADR-0022: Scoped automation administration

Date: 2026-10-10
Status: Accepted implementation of ADR-0011 authority

Expose rule/version management and run evidence only to callers with current
`automation.manage` for the exact rule workspace/project, matching existing
workflow administration. Lists select exact scope before bounded cursor paging;
run lists are bound to an authorized rule version. Drafts are never included in a
general reader endpoint. Activation continues to require organization management
and exact reviewed content. No new elevated role or delegated authority is added.
Inspection checks management permission without a write, so authorized managers
retain rule/run visibility on terminal projects. Mutations and replay preserve
the owning project's existing terminal-state write prohibition.

Run evidence contains immutable attempt/receipt metadata and target IDs, never
source event payloads, form values, recipient profiles or credentials. A target ID
does not grant access to that target; its owning API still authorizes reads.

Public replay previews the locked run and automation delivery together. Apply
requires their exact SHA-256 review and a nonblank reason, rechecks the requesting
manager and original administrator's current scope, preserves all attempt/receipt
history and refuses terminal successful runs or twenty attempts. A stale or
duplicate reviewed apply conflicts. The existing internal replay entry point is
retained for application callers. Tenant-before-evidence locking follows ADR-0017.

The initial UI provides a project metadata starter and a declarative JSON editor
for the existing typed action/condition contracts, preserving full definitions.
Server validation remains authoritative, unsupported handlers fail closed, and no
user code is evaluated. This introduces no framework, industry rule, data rewrite
or migration. Existing tables/indexes support rule/version-bound queries; further
index tuning requires measured evidence. Definition creation is an explicit new
resource command, following existing workflow APIs; save/activate/retire use
optimistic revisions and replay uses an exact review token.
