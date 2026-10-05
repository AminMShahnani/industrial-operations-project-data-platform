# Phase 2 operations

## Access and administration
Projects belong to a workspace. OrganizationAdmin needs an explicitly inherited
grant to administer projects. WorkspaceOwner/Admin can create projects; creation
seeds an audited ProjectManager membership for the creator. Existing project access
requires a project role or a valid department-project grant. Department membership
alone grants no project access. Team membership cannot receive department grants.
Revocation preserves history; reactivation does not restore old grants.

The administration UI supports project context, lifecycle preview/apply, groups,
exact-email member lookup and direct/department grants. Server permissions govern
every command. Lifecycle changes use an expected version and an audit reason.
Terminal projects are read-only. Definitions are captured immutably at creation.

Master types have immutable declarative schemas. Create a new type/code for schema
changes; never rewrite historical definitions. Record IDs/codes remain stable.
Records use status/validity rather than deletion. Decimal values are canonical text.
Location and asset registries are typed reference data, with no industry Core fields.
Milestones, forms and Domain Pack links are implemented in their owning phases.

## Tenant import/export
CSV/XLSX imports are insert-only, up to 4 MiB and 1000 records. Columns are code,
name, status, valid_from, valid_until and declared field keys; optional id is ignored
when inserting. Preview validates the entire file without writes. Apply supplies
the preview source SHA-256 and current type version; any invalid row rejects the
whole transaction. Duplicate codes reject. Date values are ISO dates; boolean values
are true/false. Formula cells, macros and external workbook links are prohibited.
Spreadsheet dimensions are treated as untrusted; actual streamed cells are bounded.

Exports include stable IDs/codes and return at most 100 records per page. Follow
X-Next-Cursor until absent. Exports are audited; CSV/XLSX formula text is escaped or
stored as literal text. Never execute imported expressions.

## Global reference publication
Only an operator with a persisted platform-admin identity in the configured trusted
OIDC issuer can publish. There is no global write HTTP endpoint. Tenant users can
read global data and cannot promote tenant data into global scope.

Example publication file (a new stable type code for each definition):

```json
{"code":"reference_units_v1","name":"Reference units","registry":"unit",
 "definition":{"fields":[]},"records":[{"code":"each","name":"Each"}]}
```

With IOP_DATABASE_URL and trusted IOP_OIDC_ISSUER configured, validate first:

```powershell
uv run python scripts/publish_global_reference.py reference.json --subject operator-subject --reason "Approved reference publication"
```

Then use the printed SHA-256 to apply the exact reviewed bytes:

```powershell
uv run python scripts/publish_global_reference.py reference.json --subject operator-subject --reason "Approved reference publication" --apply --expected-sha256 REVIEWED_HASH
```

Preview produces no writes. Apply publishes the type and all records atomically,
with immutable audit events tied to the persisted operator. Do not use this command
to modify existing global definitions or records.

## Migrations and rollback
Upgrade through 99e791752349 and 4c982bc7d8c5 with `uv run alembic upgrade head`.
The first revision creates tenant-safe projects, groups, memberships, department
grants and master data. The second protects immutable definitions, stable identities
and membership history, rejects deletion/truncation and constrains department grants
to departments. Its preflight rejects invalid existing team grants rather than guessing.

Empty-database roundtrip is tested. Both Phase 2 downgrades refuse populated Phase 2
tables before destructive changes. Never delete operational or audit history to force
a downgrade. For a populated deployment, roll back application binaries while keeping
the schema, or restore a verified pre-upgrade backup into an isolated database and
reconcile subsequent writes before an approved cutover. Production backups and
runtime database roles remain Phase 10 deployment gates.
