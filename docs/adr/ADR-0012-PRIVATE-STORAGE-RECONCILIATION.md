# ADR-0012: Private upload orphan reconciliation

Date: 2026-10-06
Status: Accepted; implements ADR-0011 and TD-005 within authorized Phase 6

## Decision
The file module owns bounded object inventory, reference checks and cleanup.
An organization administrator may preview or request cleanup only in their active
organization; platform administration grants no tenant bypass. The trusted-issuer
operator CLI follows the existing scheduling/automation CLI model, with no HTTP
bootstrap or public cleanup endpoint.

Inventory reads at most 100 objects under an exact organization prefix, with an
opaque continuation cursor. Only canonical upload paths ending in UUIDv7 qualify.
Every persisted file row is a reference, even if its attachment is unused in a
submission snapshot. Unknown paths, recent objects and all referenced files remain.
The explicit grace period defaults to 24 hours and permits 24–720 hours.

Uploads and reference insertion take a transaction-held PostgreSQL advisory lock
derived from the full object key. Cleanup tries the same lock and skips busy keys,
then rechecks database references and object age/ETag/last modification. This closes
the put-before-commit race; a grace period alone does not close it. Hash collisions
only serialize unrelated work. The runtime uses PostgreSQL READ COMMITTED so the
reference check observes the upload's committed row after acquiring its lock.
Reconciliation refuses other isolation levels instead of trusting a stale snapshot.

Cleanup requests are immutable audit intents containing typed file/workspace/
submission IDs, object ETag, modification timestamp, grace and reason. No file names,
contents, signed URLs or storage credentials enter audit/log output. The CLI commits
these intents before external deletion, then opens a separate transaction per
intent. Apply retrieves that retained evidence by tenant and intent UUID and checks
the original requester still has organization management permission. It never
trusts caller-supplied object paths. Cleanup results are immutable audit events.

Deletion uses S3 If-Match with the inspected ETag, never an unconditional fallback.
Unsupported/failed adapters record failure and preserve the intent. A crash after
deletion but before result commit leaves the requested evidence; --resume checks
the same intent, sees a missing object and records that outcome without another
effect. Changed/referenced/busy objects are preserved. External writers must obey
the same immutable-key contract; object version retention is outside orphan cleanup.

AWS documents conditional deletes for general-purpose buckets:
https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-deletes.html
The actual development S3-compatible adapter must pass conditional-delete tests.

## Migration and rollback
No schema migration or retained-data rewrite: typed fields extend the existing JSONB
audit payload, and reference lookup uses the existing unique object-key index.
Stopping the cleanup CLI preserves all files and intents. Application rollback may
stop reconciliation but must retain audit evidence. Restore mistakenly removed
objects only from a verified backup; never remove references/history to justify
deletion. This is not an attachment retention/deletion policy or pack-specific rule.
