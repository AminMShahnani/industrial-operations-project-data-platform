# Module boundaries

Composition root: `operations.main`. Technical infrastructure: `operations.platform`.
Business modules: `operations.modules.<module>` with `domain`, `application`,
`infrastructure`, and `api` subpackages. Empty namespaces express planned
ownership and do not count as completed features.

Modules: identity, organizations, workspaces, projects, iam, forms, submissions,
workflows, scheduling, tasks, automation, master_data, files, notifications,
reporting, domain_packs, integrations, audit.

Domain layers use Python standard library and their own domain only. Application
layers can use typed contracts from another module's application layer and own
domain. API/infrastructure adapt their own module; they never import another
module's persistence. Composition wires concrete implementations into application
services. Events crossing modules have typed application contracts. Tenant-owned
repositories will require organization scope in every method in Phase 1 onward.

`backend/tests/test_boundaries.py` parses imports to enforce these rules. Dynamic
imports in business modules are prohibited. New dependencies require explicit
boundary review. Namespaces are scaffolding, not permission to share tables.
