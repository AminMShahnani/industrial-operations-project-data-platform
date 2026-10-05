# Observability and Operations

## Logs
Structured JSON logs with request_id, correlation_id, organization_id (non-sensitive), actor_id where appropriate, module, event and error code. Never log form secrets/credentials.

## Metrics
HTTP latency/error rate, DB pool, queue depth, job retry/failure, schedule generation lag, automation failure, webhook failure, export duration, object storage errors.

## Tracing
OpenTelemetry context across API -> DB/outbox -> worker -> integration where supported.

## Health
Liveness, readiness and dependency diagnostics separated.

## Operations
Document backup/restore, key rotation, failed job replay, pack rollback, migration rollback, storage lifecycle and incident response.
