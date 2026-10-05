# ADR-0002: PostgreSQL as Production System of Record
Status: Accepted baseline, revisit only with evidence.

## Decision
Use PostgreSQL for production core data, with JSONB for dynamic form definitions and submission payloads.

## Rationale
The production domain is relationship-heavy and transaction-heavy, while JSONB retains controlled flexibility. This is preferable to extending the MongoDB MVP design across IAM, approvals and reporting.
