# Domain Pack Specification v0.1

## Suggested package layout
```
pack.yaml
README.md
fields/
components/
forms/
master-data/types/
master-data/seeds/
workflows/
automations/
reports/
dashboards/
roles/
integrations/
import-mappings/
locales/
migrations/
tests/
```

## Example manifest

The following is an illustrative schema-version 1 manifest. Replace its example
checksum with the lowercase SHA-256 digest of the referenced file.

```yaml
schema_version: "1"
id: com.example.oil-gas-drilling
name: Oil & Gas Drilling
version: 1.0.0
pack_type: industry
core_version_range: ">=1.0.0 <2.0.0"
dependencies:
  - id: com.example.operations-core
    version_range: ">=1.0.0 <2.0.0"
capabilities:
  - forms
  - master-data
  - workflows
  - automations
  - dashboards
content_checksums:
  - path: README.md
    sha256: 0000000000000000000000000000000000000000000000000000000000000000
publisher: Example Publisher
```

## Review-only migration descriptors

Files under `migrations/` use bounded YAML with `schema_version: 1` and an
`operations` array. Phase 8 permits only `deprecate_artifact` (artifact kind, stable
artifact ID, bounded reason) and `add_optional_field` (form or master-data type ID,
field ID, field type and label). Unknown keys, SQL, scripts, expressions and other
operations are rejected. The validated operations appear in the install/upgrade
preview and are not executed by Phase 8; artifact mutation waits for atomic services
and ownership/reference checks in the owning modules. See ADR-0036.

Version constraints use semantic-version ranges. The SDK accepts whitespace- or
comma-separated comparator clauses; for example, `>=1.0.0 <2.0.0`.

## Artifact identity
Every artifact has a stable pack-local ID and semantic artifact version where relevant. Install materializes provenance into Core.

## Validation
The schema-version 1 contract is checked in at
`contracts/domain-pack-manifest.schema.json`. Validate a local package and its file
digests with:

```powershell
uv run python scripts/domain_pack.py validate path/to/package --core-version 0.1.0
uv run python scripts/domain_pack.py schema
```

The validator uses bounded, alias-free safe YAML, rejects duplicate YAML/JSON keys,
links, hidden/path-traversal paths, unlisted files, executable/binary extensions,
bad digests, duplicate manifest entries and incompatible Core versions. The SDK
reads local folders for validation; this does not add tenant upload or remote package
installation. Phase 8 installation resolves only the curated immutable registry
under accepted ADR-0035. Pack migration content is declarative and must match an
allowlisted typed format; scripts and SQL are never executed.

The pack validator must also reject duplicate IDs, missing references, cycles, unsafe
expressions, incompatible dependencies, unknown permissions and invalid migrations.

## Upgrade
Upgrade planner reports create/update/deprecate/conflict actions. Organization-overridden artifacts are never silently overwritten.
