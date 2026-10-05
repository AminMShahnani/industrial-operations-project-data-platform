# ADR-0007: Phase 2 project access and governed master data

Status: Proposed — security decision required before implementation
Date: 2026-10-05

## Context
Phase 2 introduces projects, department memberships, department-project grants,
and reusable master data. docs/05 and 08 make projects workspace-owned and require
explicit department-project access. docs/07 requires scoped, deny-by-default
authorization and explicit inheritance. docs/14 permits global reference,
organization, workspace and project master data but does not specify who may
publish global reference data. Existing platform administration deliberately has
no implicit operational tenant permissions (ADR-0006).

## Recommended decision
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

## Pending decision
Global reference publishing is a security-sensitive ownership boundary not
selected by the source documents. Per AGENTS.md's stop condition, record the
recommended rule and obtain a decision before implementing that authority.
The remaining recommendations can be refined into accepted contracts once this
boundary is resolved. No new permissions or migrations have been applied.

## Sources
docs/03 FR-012–016; docs/05–08, 14, 18–20, 22 and 28.
