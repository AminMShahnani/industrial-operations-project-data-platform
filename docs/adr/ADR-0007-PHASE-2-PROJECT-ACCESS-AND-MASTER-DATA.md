# ADR-0007: Phase 2 project access and governed master data

Status: Accepted
Date: 2026-10-05

## Context
Phase 2 introduces projects, department memberships, department-project grants,
and reusable master data. docs/05 and 08 make projects workspace-owned and require
explicit department-project access. docs/07 requires scoped, deny-by-default
authorization and explicit inheritance. docs/14 permits global reference,
organization, workspace and project master data but does not specify who may
publish global reference data. Existing platform administration deliberately has
no implicit operational tenant permissions (ADR-0006).

## Decision
Keep tenant-owned master data governed by explicit permissions in its own scope.
Treat global reference data as platform-owned, read-only to tenant users. Publish
global reference definitions/records only through an explicit audited operator
command, with no tenant API that can promote tenant data into global scope.
Platform administration must not confer tenant master-data write access.

Department membership alone grants no project access. Only an active, valid
department-project grant combined with active department membership can confer
its explicit project role. Direct project membership remains independent.
Reject cross-tenant and cross-workspace relationships with composite foreign keys.
Preserve memberships/grants through revocation rather than deletion.

Use controlled, versioned project lifecycle definitions; validate transitions on
the server. Default states follow docs/08. Configurable metadata remains typed;
industry fields are supplied through Domain Packs in their owning phase.
Master data schemas use a bounded declarative field vocabulary; no executable
customer code. Schema changes must preserve existing record validity or require
an explicit validated migration. Imports require validation and duplicate checks
before any writes, with a dry-run preview and atomic commit.

## Authorization
The user selected audited operator publication with read-only tenant global access
on 2026-10-05. Q-003 is resolved. No tenant grant can confer global write authority.

OrganizationAdmin's existing explicit inherited grant carries project administration.
Workspace admins/owners can create projects, groups and workspace master data;
their workspace role does not automatically grant existing project operational access.
Project creation atomically seeds an explicit ProjectManager membership for its
creator, analogous to initial organization bootstrap. Further membership changes
cannot target the actor. ProjectManager can delegate only its own permissions.
Department manager flags allow management of that group's membership; an explicit
department-project role applies to active group members. Department grant changes
cannot target the actor's own department. Tenant user revocation also revokes every
direct project/group membership transactionally, including archived workspaces;
reactivation never silently restores old access.

Departments and teams share a workspace-owned group aggregate with a constrained
kind; only departments may receive department-project grants. Lifecycle graphs are
captured immutably at project creation, with all states reachable and able to reach
a terminal state. Master-data schemas are immutable after creation in Phase 2;
changed schemas use a new type/code and explicit record migration, never mutation.
Decimal values use canonical text with at most 18 integer and 6 fractional digits.
Imports are insert-only, bounded to 1000 rows/4 MiB; dry-run source hash and type
version are required for apply. Exports are cursor-paged with stable IDs/codes.
XLSX formula cells, macros, external workbook links and oversized archives deny.
CSV/XLSX exports neutralize spreadsheet formulas without evaluating expressions.
Codes remain case-sensitive stable identifiers; field keys cannot overlap built-in
record columns. Direct project or group membership permits discovering its parent
workspace name for navigation, without granting workspace management or unrelated
project/data access. Group lists are restricted to own memberships when no explicit
workspace read grant exists. Membership and department grants are independent
authorization primitives owned by their modules; IAM table access stays private.

## Sources
docs/03 FR-012–016; docs/05–08, 14, 18–20, 22 and 28.
