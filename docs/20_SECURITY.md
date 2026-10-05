# Security

## Authentication
OIDC-compatible identity architecture. Initial implementation may use first-party credentials if required, but keep authentication separate from authorization.

## Authorization
Server-side policy checks on every protected action; tenant and scope constraints mandatory.

## Secrets
Environment/secret manager only. Never persist plaintext third-party secrets in logs.

## Files
Virus/malware scanning hook, content-type validation, size limits, private object storage, signed short-lived URLs.

## Audit
Security-sensitive actions: login failures, role changes, pack installation, integration config, exports, approvals, support impersonation/access.

## Web security
CSRF strategy appropriate to auth mode, secure cookies if used, CORS allowlist, rate limiting, brute-force protection, CSP for web frontend, dependency scanning.

## Data protection
Encrypt in transit; at-rest encryption supplied by database/storage platform. Define retention and deletion policies separately from audit retention.

## Threat tests
Tenant breakout, IDOR, privilege escalation, webhook replay, malicious formula/expression, malicious upload, mass assignment, injection, broken object authorization.
