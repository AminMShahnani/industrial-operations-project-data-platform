# Testing Strategy

## Pyramid
Unit: domain rules, expression evaluator, workflow transitions, permission policies.
Integration: repositories, PostgreSQL migrations, outbox, queue, object storage adapters.
API: authz, validation, idempotency, tenant isolation.
E2E: critical browser workflows.
Contract: Domain Pack schemas, webhooks, OpenAPI compatibility.

## Mandatory suites
- tenant isolation matrix
- privilege escalation attempts
- form version immutability
- formula dependency/cycle tests
- schedule DST/timezone tests
- task occurrence idempotency
- workflow reject/resubmit/approve histories
- automation retry/idempotency
- pack install/upgrade/uninstall compatibility
- migration from MVP fixtures

## Quality gates
No phase complete with failing tests, migrations, lint, type checks or known critical security defects.
