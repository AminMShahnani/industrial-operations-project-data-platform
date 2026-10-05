# API and Events

## API style
REST/JSON V1 with `/api/v1`. OpenAPI generated and checked in CI for unintended breaking changes.

## Conventions
- UUID identifiers
- cursor pagination for high-volume lists
- RFC 7807-style problem details
- idempotency keys for selected create/command operations
- optimistic concurrency/version columns for editable definitions
- ETags optional where useful

## Command examples
POST /organizations/{id}/workspaces
POST /projects/{id}/forms
POST /forms/{id}/versions/{version}/publish
POST /tasks/{id}/start
POST /submissions/{id}/submit
POST /workflow-actions/{id}/approve
POST /domain-packs/installations:plan
POST /domain-packs/installations

## Event envelope
id, type, occurred_at, organization_id, actor_id, correlation_id, causation_id, aggregate_type, aggregate_id, payload_version, payload.

## Outbox
Transactional writes that need asynchronous side effects also write outbox rows in the same database transaction. Worker publishes/processes idempotently.
