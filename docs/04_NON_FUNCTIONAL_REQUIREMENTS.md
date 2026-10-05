# Non-Functional Requirements

## Availability and durability
- Target V1 application availability: 99.9% excluding planned maintenance.
- Daily verified backups; production RPO target <= 24h initially, configurable lower for enterprise.
- Restore procedure must be tested.

## Performance
- Typical authenticated API p95 <= 500 ms excluding large exports/integrations.
- Form render metadata retrieval p95 <= 750 ms.
- Task inbox first page p95 <= 1 s under target production dataset.
- Large reports/exports run asynchronously.

## Scale assumptions for initial architecture
Per organization: up to 10k users, 1k projects, 10k active form definitions/versions, millions of submissions. Architecture must not rely on loading all submissions into memory.

## Security
- least privilege and deny-by-default authorization
- encryption in transit and at rest
- tenant isolation tests
- immutable security/audit events
- secret management outside source code

## Maintainability
- modular boundaries
- typed APIs
- database migrations
- automated tests
- ADRs for significant decisions
- no customer-specific conditionals in Core

## Internationalization
Store UTC timestamps; present in configured timezone. UI strings prepared for localization. Units separated from values where practical.

## Accessibility
Target WCAG 2.1 AA for primary web workflows.
