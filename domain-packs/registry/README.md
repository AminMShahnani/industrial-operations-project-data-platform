# Curated Domain Pack registry

This directory is the platform-managed, immutable-at-runtime package catalog.
Curators add reviewed releases as `<pack-id>/<semantic-version>/` directories.
Each release must contain `pack.yaml` and every content file referenced by its
checksums. Do not add uploaded customer packages, arbitrary remote references,
executable scripts or SQL migrations. Code review and the package validator establish
the registry trust boundary; publisher signatures are not configured in Phase 8.

The SDK can validate a local package folder, but installation resolves only content
present in this curated directory. Installed packages are organization scoped under
ADR-0035.
