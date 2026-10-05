# Migration from Existing MVP

## Current MVP observed
FastAPI + Beanie/MongoDB. Core documents: Form, FormVersion, Schedule, Occurrence, Submission. Authentication/tenant context is hardcoded. Dynamic fields/tables, basic RRULE expansion and submission storage are present.

## Known MVP defects to avoid carrying forward
- hardcoded tenant/user dependencies;
- `active_version` vs `activeVersion` mismatch;
- schedule route constructs all occurrences but inserts only the last one;
- submission route may reference `occ` before assignment;
- weak tenant scoping in object lookup;
- mutable-list/dict defaults in models;
- schedule/occurrence `Settings` placement appears incorrect;
- no authoritative submission validation against form version;
- no real authorization, workflow, audit or organizational hierarchy.

## Migration principle
Treat MVP as data/behavior reference, not architectural base.

## Migration path
1. inventory existing Mongo collections and production data, if any;
2. define mapping from Form/FormVersion to new immutable form definitions;
3. map Schedule to ScheduleVersion and generated tasks;
4. map Occurrence to TaskOccurrence;
5. map Submission payloads to new submission records with preserved original IDs in migration metadata;
6. create organization/workspace/project scopes for legacy data;
7. validate record counts/checksums;
8. run parallel read validation before cutover.

## Compatibility
Do not preserve broken route shapes solely for old demo clients unless explicitly required. If needed, create a temporary compatibility adapter with deprecation date.
