# Phase 5 workflow operations

Status: accepted on d91dfce; all 8 Phase 5 criteria pass.
CI: https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37454353238

## Migration and deployment
The Phase 5 chain follows `b71acf0449b2`: `e049d194ba38` definitions,
`1223fa111b4c` runtime, `c4f0276864fa` revisions/task guards,
`20bfc93ae828` evidence/bounds and `71db385e7a02` scoped review roles.
Run `uv run alembic upgrade head` with the intended `IOP_DATABASE_URL`, then
`uv run alembic check`. Keep production deployment behind Phase 5 acceptance.
Existing submissions remain intact; activation never backfills approval history.

## Administration and operation
Managers create typed drafts against a published form version, preview validated
activation, then apply the reviewed content hash and optimistic revision. One
active binding exists per form version. Replacement retains pinned instances.
The UI offers ordered one/all/quorum/sequential approvers and advanced graph editing.
Typed APIs support review, decision, notification and explicit return nodes.
Unsupported manager relationships fail explicitly; never invent substitutes.

Assigned users review permitted immutable evidence in the scoped inbox. Every
action requires a reason and immutable actor/time/audit evidence. ADR-0010 requires
independent approval, including administrators. Assignment snapshots never bypass
fresh identity, group/role or project checks. Drafts remain private. Basic authenticated
acknowledgement is V1; configurable signatures remain V1.5.

Owners create correction drafts of returned/rejected records and amendments of
approved records, preserving originals and supplying fresh evidence. Shared tasks
retain the original pointer and follow authoritative workflow states through the
revision chain. Previous-approved defaults use exact scope, form and owner.
Graphs permit 100 nodes/200 transitions without forward cycles; explicit returns
create distinct visits. Visits/recipient sets are bounded to 1000; history pages
contain 20 visits/100 actions. Typed notification intents hand off to Phase 6 delivery.

## Rollback
Each migration checks retained data before weakening guards or dropping evidence.
Populated runtime/revision/definition downgrade refuses. Review-role downgrade
refuses if Reviewer/Approver grants remain, including revoked grants. Never delete
history or rewrite roles to force downgrade. Stop writes, retain verified database
and object-store backups, restore compatible application/schema together and
reconcile post-backup records. Keep forward schemas for compatible code rollback.
Do not reset retained development/browser databases to bypass populated guards.
