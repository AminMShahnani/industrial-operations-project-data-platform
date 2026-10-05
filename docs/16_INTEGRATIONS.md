# Integrations

## Integration framework
Adapters implement outbound/inbound contracts. Credentials are tenant-scoped secrets.

## V1
- SMTP/email provider abstraction
- webhook subscriptions
- object storage
- Excel/CSV import/export

## Future
SSO/SAML/OIDC enterprise identity, SCIM, ERP, CMMS/EAM, SharePoint/Drive-like DMS, messaging, BI warehouse, industry protocols.

## Webhooks
Signed payloads, retries, delivery logs, idempotency IDs. Subscriptions are scoped and permissioned.

## Oil & Gas mapping targets
Oil & Gas Domain Pack should reserve mapping layers for WITSML-compatible well/site data and drilling report standards. Do not couple Core tables to these standards.
