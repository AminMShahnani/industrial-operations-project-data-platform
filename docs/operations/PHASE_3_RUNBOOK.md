# Phase 3: forms, submissions and files

## Local setup
Run the foundation and identity setup in README.md and IDENTITY_RUNBOOK.md.
Upgrade with `uv run alembic upgrade head`, then start the API and frontend.
Form Studio appears in the selected workspace/project context. Workspace owners
and admins manage workspace forms; project managers manage project forms. Explicit
inherited organization administration covers both. Contributors create their own
drafts; viewers read published definitions. Platform operators have no implicit
tenant access.

## Build, reuse and publish
The builder supports sections, a component palette, properties, structure ordering,
JSON definition import, reusable fields/sections/form starters, preview and history.
UI import files are limited to 1 MiB. Server contracts and the actual 8 MiB request
limit remain authoritative for all clients. Imports edit drafts only; publication
resolves exact library pins into a validated immutable executable snapshot.
Library code identifies a logical artifact; each numbered immutable artifact has
its own UUID. References require that UUID and matching version number.

Example definition for API creation or JSON import:

```json
{"schema_version":1,"sections":[{"key":"main","label":"Report","components":[
 {"key":"count","kind":"integer","label":"Count","required":true},
 {"key":"double","kind":"calculated","label":"Double","formula":
  {"op":"multiply","args":[{"op":"field","key":"count"},{"op":"literal","value":2}]}}
]}]}
```

Component keys are stable lowercase identifiers. V1 covers text/textarea, integer,
decimal, boolean, date/datetime/time, selection/radio/multiple selection, user,
department/project/master lookups, file/image, signature acknowledgement,
calculated scalar, table/repeating group and display/instruction families.
Definitions are bounded to 30 sections, 100 resolved components, 30 children per
repeating component and 100 rows. Nested repeating groups are rejected.
Decimals use bounded canonical text; datetimes must be timezone aware.

Save using the expected revision. Preview publication validates references,
expressions, cycles and static defaults. Apply requires the reviewed definition
SHA-256 and unchanged revision. Published definitions cannot be edited, including
at the database level. Clone into a new numbered draft for changed behavior.
Deprecation prevents new drafts and lets existing ones continue. Retirement blocks
all draft writes. Lifecycle actions use preview, expected revision and a reason.
Submitted snapshots remain readable after either transition.

## Expressions, defaults and permissions
The JSON AST supports literal, field/context references, arithmetic, comparisons,
strict boolean operations, if/coalesce, concatenation, length and bounded rounding.
No source strings, arbitrary customer code or external calls execute. Expressions
are limited to 200 nodes and depth 12. Definitions reject unknown references,
dependency cycles and expressions exposing a more restricted field. Calculated
values are server-owned and recalculated during validation/submission.

Static, current user, organization-local current date, UTC current datetime,
current project and configured master-record defaults are available. Trusted
DefaultContext application ports support shift and previous-approved values.
Their authoritative providers belong to scheduling (Phase 4) and workflow (Phase 5).
Until connected, initialization reports unavailable context explicitly; submitted
records are never treated as approved. Users can fill eligible fields manually.

Field read/write policies narrow existing access to eligible actors, draft owner
or scope manager. Hidden fields are removed from previews and response snapshots.
Autosave preserves server-owned read-only values and rejects attempted changes.
User lookup requires exact email and an active identity with effective form-read
access in the target scope. Lists are bounded and cursor-paged. Configured master
lookups expose names/IDs of their own type, never unrelated record payloads.

## Drafts and submitted history
Drafts bind the exact FormVersion ID/number, tenant/workspace and owner. Runtime
autosave waits 1.2 seconds of inactivity, uses optimistic concurrency and stops
automatic retries after invalid input until another edit. Validate displays field
issues. Save before submitting; submit requires an idempotency UUID and reason.
Matching retries return the preserved snapshot without another write/audit.
Submitted records preserve values, source version, timestamp, checksum and
authenticated signature evidence, including repeating rows. Drafts remain private
to their owner. Managers may read submitted snapshots subject to field policies.
Acknowledgement does not claim a qualified cryptographic/legal signature;
configurable signing stays V1.5. Workflow routing and amendments belong to Phase 5.

## Private attachments
Configure IOP_SCANNER_HOST and IOP_SCANNER_PORT for a trusted ClamD service.
Missing/unreachable scanners return 503; malware returns 422; unknown/failed
responses deny availability. API clients cannot configure scanners or storage.
Follow [official ClamAV Docker setup](https://docs.clamav.net/manual/Installing/Docker.html)
and provision a patched supported scanner on a trusted private network. The adapter
uses [INSTREAM](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).
Configure StreamMaxLength at least 5 MiB and maintain signature updates.
Provider deployment and engine maintenance remain operational responsibilities.
Tests verify streamed scanner responses, denial paths and actual private storage;
they do not replace production engine/signature deployment validation.

Uploads require an owned writable draft and an allowed file/image component.
Limits: 5 MiB, sanitized filename, text/plain or PDF/PNG/JPEG with byte-signature or
UTF-8 validation. Only a positive scan reaches private storage. Immutable metadata
records owner, parent scope, content type, size and SHA-256. Composite foreign keys
reject an owner differing from the parent draft. Files cannot be attached across
drafts or tenants. Downloads reauthorize parent and field visibility, use attachment
disposition and signed 60-second URLs. Managers can download only actual file/image
references in the visible snapshot. Production S3 endpoints must be client-reachable
and use HTTPS.

Failed database writes compensate only freshly generated keys from that request.
If cleanup fails, objects remain private and unavailable through the API.
Inventory/reconciliation backstop is TD-005 for Phase 6. Committed operational files
must never be deleted to force rollback.

## Migration and rollback
464245e2e729 creates forms, versions, libraries, submissions and files. Composite
foreign keys, checks and update/delete/truncate triggers protect ownership,
published definitions, submitted snapshots and history. Empty roundtrip is tested.
Populated downgrade refuses before destructive operations.
dbd58764eb86 adds attachment-owner integrity and indexed email/submission reads.
Preflight rejects mismatched owners without rewriting data; populated file downgrade
refuses before weakening the constraint.

For populated deployments, roll back application binaries while retaining schema,
or restore a verified pre-upgrade backup into an isolated database and reconcile
subsequent writes before approved cutover. Never delete history or audit to force
downgrade. No legacy export or operational migration was supplied. Production
backup/restore, retention, quotas and deployment trust remain Phase 10.

## Validation
Run scripts/check.ps1 with both isolated database URLs and oidc-dev enabled.
Gates cover version immutability/cycles, scope/privacy, upload ownership/rollback,
real private storage/signed download, real Chromium PKCE/publication/autosave/submit,
migration roundtrip/drift, lint/types, generated contracts, tests and production build.
