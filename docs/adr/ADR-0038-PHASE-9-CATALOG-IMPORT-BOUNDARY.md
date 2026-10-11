# ADR-0038: Organization pack catalog and explicit workspace import

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 8 installs Domain Packs at organization scope. Forms and workflows belong to
workspace/project scopes, while reports and dashboards are private to their creator.
Implicitly installing pack artifacts into every workspace would bypass ownership,
permission and audit boundaries in their owning modules.

## Decision

An organization installation makes immutable, curated pack content available in the
organization catalog. A user with the owning module's scoped management permission
must explicitly select and preview each artifact import into a workspace or project.
Imports use the owning application service, preserve source pack/artifact/version
provenance and append immutable audit. Form and workflow imports create drafts only;
publication/activation remains a separate authorized action. Private report and
dashboard templates are instantiated as creator-owned definitions.

## Consequences

- Installing a pack does not create objects across existing or future workspaces.
- Import previews bind to the immutable registry package digest and selected target
  scope; apply rechecks both the digest and current authorization.
- Imported copies can evolve through existing owning-module versioning. Provenance
  identifies the source without making a tenant copy vendor-editable.
- No module may read another module's persistence directly for import/materialization.
