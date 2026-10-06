# Phase 5 workflow operations

Status: implementation in progress; runtime/API rollout not accepted.

## Definition migration
`e049d194ba38` follows `b71acf0449b2`. It adds scoped workflow identities and
version definitions. Activated versions pin exact form versions and are immutable;
retirement retains historical content. Definitions are typed declarative graphs,
never executable user code. There is no workflow API exposed by this foundation
change and submission behavior is not yet wired to workflow instances.

Run `uv run alembic upgrade head` with the intended `IOP_DATABASE_URL`. Verify
`uv run alembic check` afterwards. Keep production deployment behind Phase 5
acceptance: action authorization, revisions, task transitions and browser/UI gates
are still required.

## Rollback
Downgrade is permitted only when both new tables are empty. The migration checks
before dropping any table and refuses populated rollback. Never delete workflow
definitions or evidence to force downgrade. For populated deployment rollback,
stop writes, retain a verified database/object-store backup, restore compatible
application/schema together and reconcile any records created after the backup.
Keep the forward schema when rolling back application code that does not use the
new tables. Existing submissions, files, tasks and schedules are not rewritten.

## Approval policy
ADR-0010 requires independent approval, including administrators. Assignment
snapshots must not grant access. Runtime implementation must recheck current
identity and scoped authority for every action, reject empty independent-approver
sets and preserve immutable action reasons, signer identity and timestamps.
