# Multi-Tenancy

## Boundary
Organization is the primary tenant boundary.

## Isolation
Every tenant-owned relational row must have `organization_id` directly or through a guaranteed parent relation. Sensitive tables should include direct tenant keys where this simplifies policy enforcement and indexing.

## Strategy
V1: shared database/shared schema with strict tenant keys and application-level repository scoping. PostgreSQL Row Level Security may be introduced as defense-in-depth after repository contracts are stable.

## Requirements
- requests resolve authenticated organization context explicitly;
- no repository method returns tenant-owned records without tenant scope;
- background jobs carry organization context;
- cache keys include organization ID;
- object storage paths include organization ID and non-guessable IDs;
- webhook secrets/integration credentials are tenant-scoped;
- tenant isolation tests are mandatory.

## Cross-tenant platform super admin
Platform support access must be explicit, audited, time-bounded where possible, and never implemented by bypassing all policy checks invisibly.
