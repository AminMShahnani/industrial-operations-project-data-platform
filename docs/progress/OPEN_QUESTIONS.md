# Open Questions

## Phase 6 webhook security boundary (resolved)

- Q-009 (2026-10-10): Resolved when the user selected the documented
  recommendation with “do”. ADR-0026 is accepted: immutable scope-bound endpoint
  versions; HTTPS; external tenant secrets; no redirects; validated and pinned
  destination addresses; deployment-managed CIDR exceptions for private industrial
  endpoints; and a fixed identifiers-only signed envelope. Scalar event fields are
  excluded. Runtime delivery remains fail-closed until its external secret resolver
  and safe transport are implemented.

Controlled project annotations (2026-10-10): ADR-0025 uses existing project.read/
manage and accepted automation delegation for inert append-only labels. Labels do
not alter access, lifecycle or record approval. No new unresolved security/domain
question; unsupported target scopes fail explicitly. All local gates pass (298
backend/18 frontend tests). Hosted
[38057404691](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38057404691)
passes both jobs on exact code b5e4581a80586b95960cdb192e83a6fadbf53d2d.

## Phase 6 generic task completion (resolved)

- Q-008 (2026-10-10): May an eligible claimant finish a generic task by acknowledging
  completion, or must an independent reviewer approve it? docs/12 distinguishes
  generic/form tasks; docs/11 does not specify generic completion authority.
  Recommended: a distinct completed state with fresh claimant authorization and
  immutable audit, without submission/record approval. Governed work continues
  through form tasks and independent workflows. User selected the recommendation
  with "do your recommandation" on 2026-10-10. ADR-0024 is accepted; implementation
  proceeds without reopening independent record approval.
  Implementation passes all local gates (285 backend/18 frontend tests), including
  real PKCE execution, committed worker/claim/completion concurrency and guarded
  migration rollback. Hosted run 38052949486 passes both jobs on exact code d25ad7a; no new
  unresolved authority decision is introduced.

## Phase 6 invitation email decision (resolved)
- Q-007 (2026-10-10): Select acceptance for durable invitation emails. ADR-0006
  stores only token digests; ADR-0011 prohibits plaintext tokens in outbox/broker
  payloads. Recommended: token-free sign-in and a distinct new invitation mode
  requiring matching OIDC-verified email and fresh inviter authority. Preserve
  existing bearer-token invitations. Alternative: authorize temporary encrypted
  token storage with explicit key, retention and replay policy. ADR-0019 is
  accepted: user delegated with "do best" on 2026-10-10. Select the recommended
  token-free verified-email mode; existing token invitations stay unchanged.
  Lifecycle/API/browser implementation passes local gates (227 backend/14 frontend)
  and hosted run 38036138271 on exact final code 82cf4e5. SMTP delivery remains
  current-phase work under ADR-0011, with no new unresolved security decision.

## Phase 0 blockers
None. Remote configuration and required hosted CI are resolved.

## Resolved Phase 1 security decision
- Q-002: Select the initial trusted identity provider or explicitly require
  first-party credentials. Define organization identity linkage, platform-admin
  bootstrap, invitation verification and token/session trust requirements.
  docs/20 permits alternatives but does not select a deployment trust model.
  Do not introduce a temporary authentication bypass to avoid this decision.
  User asked on 2026-10-05 to select configurable OIDC or first-party credentials;
  User delegated the choice: OIDC selected in ADR-0006; question resolved.

## Questions that do not block Phase 0
- job queue library choice;
- exact enterprise deployment topology (cloud/on-prem/hybrid);
- retention requirements by customer/industry;
- legal requirements for electronic signatures in target markets.

## Resolved
- Repository remote: https://github.com/AminMShahnani/industrial-operations-project-data-platform
- Q-001: `main` tracks `origin/main`; hosted run 37316897694 passes both jobs.
- Frontend: React SPA with Vite, strict TypeScript (ADR-0004).
- Repository inventory: docs only; legacy code and production data not supplied.

Codex must not guess business-critical answers. Record assumptions and use configurable abstractions when possible.

Phase 1 final hosted run 37325939172 passes. No unresolved Phase 1 question.

## Resolved Phase 2 security decision
- Q-003: User selected audited operator publication on 2026-10-05.
  Global reference data is read-only to tenants; platform administration never
  grants tenant operational access. ADR-0007 is accepted. No unresolved Phase 2 blocker.

## Phase 3 decisions
No unresolved security-sensitive Phase 3 question. ADR-0008 records scoped privacy,
restricted fields, declarative evaluation, immutable snapshots and fail-closed files.
Basic authenticated acknowledgement is V1; configurable signatures stay V1.5.
Shift and previous-approved defaults have trusted ports; authoritative records are
owned by Phase 4/5, with explicit unavailable-context errors until connected.

## Resolved Phase 4 assignment decision
- Q-004 (2026-10-06): For team, department, scoped-role and shift targets, is one
  occurrence shared and claimed/completed by one eligible member, or does every
  eligible member receive a separately completed task?
  docs/11 specifies deterministic recipients and assignment snapshots but not
  group completion/claim semantics. This changes task uniqueness, claim authority,
  submission ownership and whose work is satisfied by a submission.
  Recommended: one shared task per assignment scope with an atomic single-member
  claim, eligible-recipient snapshot and fresh permission checks on every action.
  Alternative: separately materialized tasks per eligible recipient.
  User selected the recommended shared claimed task on 2026-10-06.
  ADR-0009 accepted. No unresolved Phase 4 assignment blocker.

Phase 4 accepted on d92a10f with hosted run 37432881526. No unresolved Phase 4
security/domain question. Workflow policies are reviewed before Phase 5 implementation.

## Phase 5 security decision (resolved)
- Q-005 (2026-10-06): May a submitter approve their own record? docs/10 does not
  establish separation of duties. Recommended: require independent approval and
  never silently substitute an administrator when no eligible approver exists.
  Alternative: permit self-approval only when explicitly configured in a workflow.
  User accepted mandatory independent approval; ADR-0010 is accepted.

Q-005 resolved on 2026-10-06: user instructed "do it" after the independent-approval
recommendation. ADR-0010 accepted. Submitters cannot approve their own record,
including administrators; no definition-level opt-out or silent reassignment.

Phase 5 runtime verification: no new unresolved security/domain question.
ADR-0010 records exact-version binding, preserved revisions, scoped action roles,
fresh authority, deterministic routing and bounded history. Unsupported manager
relationships fail explicitly rather than inventing domain data.

Phase 5 accepted on d91dfce / hosted run 37454353238. No unresolved Phase 5
security/domain boundary; Phase 6 decisions remain subject to its own preparation.

## Phase 6 security decision (resolved)
- Q-006 (2026-10-06): Whose authority executes background automation? docs/12
  requires elevated permission for governance-changing actions but does not define
  the worker principal. Recommended: activating administrator's bounded delegated
  authority, with fresh checks on each run. Alternative: dedicated tenant service
  identity with explicit scoped grants. User selected the recommendation with
  "Do your recommendation" on 2026-10-06. ADR-0011 accepted. No unresolved
  execution-authority question; implementation proceeds with fresh delegated checks.

Delegated-ledger checkpoint: fresh authority, revocation and replay checks now have
application-service integration tests. No new unresolved domain/security decision.
ADR-0011 records atomic capture-time matching and retained execution evidence.

Local and hosted ledger verification pass on e1e84af / run 37462108788. Q-006 stays
resolved; remaining Phase 6 work does not require reopening its authority decision.

Action/consumer increment: no new security/domain ambiguity. ADR-0011 records
exact workflow action pins, source privacy, task materialization receipts and atomic
consumer/savepoint boundaries. Q-006 delegation is verified by real worker tests.

Action/worker hosted verification passes on 700db02 / run 37465763364. The final
workflow application-boundary refinement introduces no new domain decision.

Final refinement 4f8f6da passes hosted run 37466610016. No unresolved question blocks
the next Phase 6 implementation work; Q-006 remains resolved.

Private-storage reconciliation: ADR-0012 implements the already required TD-005
boundary using current tenant administrator authority and the existing trusted CLI
model. Grace, reference preservation, upload serialization, conditional deletion and
retained intent replay are explicit and tested. No unresolved domain/security question
or new tenant/platform access bypass; no retained data was migrated or rewritten.

Reconciliation passes hosted run 37480916988 on adea461. No new unresolved question;
Phase 6 remains in progress under the existing resolved authority decisions.

Periodic trigger generation: ADR-0013 records activation-aligned cadence, bounded
catch-up, exact timer matching and once-per-task due/overdue evidence. Q-006's
delegator authority is preserved, with a separately authorized scoped operator.
No private draft access, lifecycle shortcut, industry coupling or unresolved new
security/domain decision. Compatibility preflight found no stored unpinned timer
events in the three local databases; no historical envelope was rewritten.

Periodic code 3beb19d passes hosted run 37499621510. No new unresolved security/
domain question or Phase 7 work; existing authority decisions remain in force.


ADR-0014 implements in-app automation notices under existing Q-006 authority.
Fresh source-owning service checks, original task assignment eligibility and
recipient-only inbox/read access retain the accepted privacy boundary. No new
unresolved security/domain question, retained-data rewrite or industry coupling.
Automatic notification/email/invitation policies remain required Phase 6 work.

Hosted 37504095044 passes both jobs on notice code 11b7818. No unresolved
question or change to the existing authority decisions; Phase 6 remains open.


Automatic in-app delivery: ADR-0015 records fixed source authority, original plus
live recipient eligibility, system-actor audits and bounded atomic delivery.
Notification eligibility does not grant review votes or submission content access.
No new unresolved security/domain boundary; Core remains industry-neutral.
Pre-outbox historical handoffs require bounded audited reconciliation rather than
an inferred reminder/audit mapping or rewriting retained history. This is current
Phase 6 work, along with controlled replay/email/invitations, not a Phase 7 deferral.
Automatic delivery verification: hosted run 37511023333 passes both jobs on
2cebf5e after all local gates pass (195 backend/11 frontend tests). No additional
security-sensitive question is introduced; Phase 6 remains unaccepted.

Controlled notification replay: ADR-0016 uses the existing trusted operator model
with fresh organization.manage and scoped automation.manage checks. Reviewed state
comparison, twenty-attempt cap and terminal completed deliveries preserve ADR-0015.
No unresolved authority decision or Core industry coupling is introduced.
Historical handoff reconciliation remains a separate provenance-preserving slice.
ADR-0017 records the tenant-before-identity locking repair for a reproducible browser/
invitation deadlock. It preserves existing authorization and revocation serialization;
no domain or security policy is changed.
Hosted run 37514426474 passes both jobs on exact code ffac30f after all local
gates pass (203 backend/11 frontend). No additional unresolved question is introduced.

Historical notification handoffs: ADR-0018 records reviewed, bounded reconciliation
of exact retained notify/reminder intents under existing administrator authority.
Current reconciliation events/audits preserve original IDs and creation timestamps;
no historical actor or reminder-to-audit association is inferred. Existing captured
handoffs stay terminal, and recipient eligibility is checked by the worker. No new
unresolved security/domain decision or industry coupling is introduced.
All local gates pass (215 backend/11 frontend); hosted run 37519811189 passes both
jobs on exact code 079b8c8. Phase 6 stays unaccepted with no unresolved new question.

## SMTP delivery increment - 2026-10-10

ADR-0020 records explicit organization-admin queue intent, fresh original delegation,
source-owning eligibility, external tenant secrets, uncertain-send recovery and
exact reviewed replay. It does not enable automatic opt-in/backfill or rule email
channels. No unresolved security/domain boundary or industry coupling is introduced.
All local gates pass (240 backend/14 frontend tests); hosted run 38042281045
passes both jobs on exact code ee70500. Phase 6 remains open.

## Explicit email source capture - 2026-10-10

ADR-0021 uses the existing organization-admin delegation for explicit invitation
requests and activated rule channel lists. Email-only evidence is retained privately;
no mailbox delivery claim, tenant-wide opt-in, historical backfill or source identity
bypass is introduced. Task/workflow email uses explicitly activated notify rules,
preserving fixed automatic in-app projections and existing delegated authority.
No new unresolved security/domain question. All local gates pass (250 backend/
14 frontend tests); hosted run 38044650329 passes both jobs on exact code 6fd5082.

## Automation administration - 2026-10-10

ADR-0022 exposes existing scoped management/delegation, management-only drafts and
minimal run evidence. Public replay adds exact state review and a reason without
changing the approved authority or attempt limits. No unresolved domain/security
question or industry coupling is introduced. All local gates pass (261 backend/16 frontend tests); hosted run 38047837127
passes both jobs on exact code fe4ebc8. No phase acceptance gate is waived.

## Email recovery console - 2026-10-10

ADR-0023 uses existing organization-admin email authority and original delegation.
Minimal evidence remains inspectable when a source expires or authority changes;
this confers no source-read/send authority. Public uncertain replay requires explicit
possible-duplicate acknowledgement. No new domain/security ambiguity or industry
coupling. All local gates pass (272 backend/18 frontend tests); hosted run 38049979000
passes both jobs on exact code b0b9d05. No new unresolved question.
