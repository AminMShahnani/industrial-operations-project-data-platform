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
```yaml
id: com.example.oil-gas-drilling
name: Oil & Gas Drilling
version: 1.0.0
pack_type: industry
core_version: ">=1.0.0 <2.0.0"
dependencies: []
capabilities:
  - forms
  - master-data
  - workflows
  - automations
  - dashboards
publisher: Example
```

## Artifact identity
Every artifact has a stable pack-local ID and semantic artifact version where relevant. Install materializes provenance into Core.

## Validation
Pack validator must reject duplicate IDs, missing references, cycles, unsafe expressions, incompatible dependencies, unknown permissions and invalid migrations.

## Upgrade
Upgrade planner reports create/update/deprecate/conflict actions. Organization-overridden artifacts are never silently overwritten.
