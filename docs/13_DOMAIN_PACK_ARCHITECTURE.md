# Domain Pack Architecture

## Goal
Enable rapid deployment to a new industry or organization without changing Core or creating customer forks.

## A Domain Pack may contain
- metadata/manifest
- dependencies and compatibility constraints
- field definitions and reusable components
- form templates
- master-data schemas and seed/reference data
- workflow templates
- automation templates
- role/permission presets
- dashboards/KPIs
- report templates
- validation rules
- terminology/localization overlays
- integration mapping profiles
- Excel import mapping profiles
- migration scripts in a constrained pack migration format
- documentation and examples

## Pack types
1. Industry Pack — e.g. Oil & Gas Drilling, Construction.
2. Functional Pack — e.g. HSE, Maintenance, QA/QC.
3. Organization Overlay — customer-specific terminology, forms, mappings and branding, depending on one or more base packs.

## Composition
Packs may depend on packs. Example:
`org-acme-drilling` -> `oil-gas-drilling` -> `core-operations`.
Avoid circular dependencies.

## Manifest
Required fields:
- id (reverse-DNS or namespaced slug)
- name
- semantic version
- pack_type
- core_version_range
- dependencies
- capabilities
- content checksums
- publisher
- signature metadata (future enterprise)

## Installation lifecycle
available -> validating -> installed -> enabled -> upgrading -> disabled -> uninstalling.

Install must perform:
1. compatibility check;
2. dependency resolution;
3. dry-run diff;
4. schema/content validation;
5. transactional metadata installation where possible;
6. post-install verification;
7. audit event.

## Versioning
Semantic versioning.
- patch: compatible corrections/content.
- minor: additive compatible templates/capabilities.
- major: potentially breaking pack contracts requiring migration review.

## Customization rule
Never edit vendor pack artifacts in place. Organization customizations are overlays or cloned organization-owned templates with provenance metadata.

## Uninstall rule
Pack uninstall cannot delete operational submissions. It may disable templates and remove unreferenced configuration only. Historical records retain pack/version provenance.

## Pack SDK
Repository should eventually provide:
- JSON/YAML schemas
- validation CLI
- local preview/test harness
- dependency resolver
- pack scaffold generator
- migration linter
- sample packs

## Storage
Pack source artifacts live in a registry/repository. Installed pack metadata and materialized domain artifacts live in application storage with provenance:
`source_pack_id`, `source_pack_version`, `source_artifact_id`.

## Governance
Only authorized organization admins can install packs. Pack operations are audited. Production should support trusted publisher policies.
