# ADR-0035: Phase 8 Domain Pack trust and execution boundary

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 8 introduces the Domain Pack manifest, registry, dependency/version/install
engine and SDK validation. The architecture requires checksums, publisher metadata,
a constrained migration format and audited installation. It describes signature
metadata as future enterprise work, but does not identify trusted registry sources,
whether organizations may submit their own packages, or what a pack migration may
execute. These choices determine the install threat boundary.

## Decision

For Phase 8, resolve only packages from a curated, immutable registry whose package
contents are reviewed and checksum-pinned. Do not accept tenant uploads or fetch
arbitrary remote packages. Packs contain declarative content only; migrations use
an allowlisted typed operation format and cannot run SQL, Python, JavaScript, shell
commands or other arbitrary code. Publisher signatures and configurable trust roots
remain future work until their key lifecycle and revocation policy are specified.

Start with organization-scoped installations managed by an authorized organization
administrator holding `domain_pack.install`. Workspace/project materialization is
not inferred; enable those scopes only after their override, sharing and provenance
rules are defined. Every lifecycle command uses a dry-run plan and emits immutable
audit evidence.

Installations retain immutable per-release provenance. Phase 8 does not yet link
materialized forms, workflows, records or other operational artifacts back to a
pack, so uninstall is conservatively refused once release provenance exists; it
must not delete operational data. Disable remains available to stop use of the
installed pack. A later artifact-provenance design may safely relax this guard.

## Consequences

- Phase 8 can provide validation and installation without a general code execution
  path or an undefined remote-publisher trust root.
- The registry is deliberately narrower than a public marketplace. Uploads,
  external sources, signatures and workspace/project scoped installs require a
  later accepted decision.
- Core remains industry-neutral; packs provide declarative industry semantics.
- The project owner selected the curated registry/declarative content boundary and
  organization-only installation scope on 2026-10-11.

## Alternatives

- Accept uploaded or remote packages now: rejected because no
  publisher trust-root, signature verification or revocation lifecycle is defined.
- Permit arbitrary migration scripts: rejected because pack content must not become
  an application code execution path.
- Allow install scopes to be selected without separate overlay/provenance rules:
  rejected because the documents do not define how nested scope overrides compose.
