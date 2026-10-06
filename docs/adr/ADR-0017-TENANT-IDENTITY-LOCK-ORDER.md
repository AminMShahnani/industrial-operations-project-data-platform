# ADR-0017: Tenant-before-identity lock ordering

Date: 2026-10-06
Status: Accepted concurrency repair; authorization policy unchanged

## Evidence and decision

Repeated real PKCE browser tests exposed a PostgreSQL deadlock between an audited
invitation setup transaction (organization then user) and a live API transaction
(user then organization). Waiting for browser network idle did not fix it. This
ordering also affects normal concurrent application callers.

Identity persistence now obtains the owning organization's existing row lock through
an explicit application lock contract before locking a scoped user by principal or
ID. Composition supplies the organization-owned adapter; identity imports no foreign
table or persistence implementation. Existing organization reads already hold an
exclusive row lock, so this makes the order consistent without removing revocation
serialization or broadening authorization. Missing/inactive identity semantics and
caller-specific organization lifecycle policy remain unchanged.

Automation/notification workers and dispatch also obtain the tenant lock through
the owning organization application service before locking deliveries or runs.
This prevents worker-delivery-first versus administrator-tenant-first replay inversion.

The existing lock is acquired earlier and held until transaction completion. This
preserves current tenant-level serialization; optimizing that contention requires
separate measurement and a reviewed concurrency design. Cross-tenant operations
still need explicit scoping and must not take arbitrary tenant locks in mixed order.

No schema or stored-data change. Verify real browser invite/submit/review flows,
concurrent committed replay and existing revocation/concurrency suites before commit.
