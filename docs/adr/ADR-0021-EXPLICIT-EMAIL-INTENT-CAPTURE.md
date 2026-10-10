# ADR-0021: Explicit email intent capture

Date: 2026-10-10
Status: Accepted implementation of ADR-0011/0019/0020 within Phase 6

Verified-email invitation creation may explicitly request email with an audit
reason. Current organization.manage is required in addition to invitation delegation.
Invitation creation and deterministic email intent/audit commit together; retries
preserve the same invitation and delivery. Omitting email never cancels existing
intent. Existing token invitations and default manual sharing remain unchanged.

An activated notify action's immutable channel list authorizes in_app, email, or
both, with unique channels. Its currently authorized activating administrator queues
the exact retained notice/recipient inside the automation run savepoint. Never send
SMTP or publish Redis inside the source transaction. Email configuration is checked
by the separate dispatcher/worker; queue capture remains durable while disabled.
Fresh original delegation and source/recipient authorization govern every send.

Retain a minimal notice for every selected recipient as source evidence. The immutable
in_app bit reflects the exact activated channel list: email-only notices are excluded
from inbox/detail/read and cursor pagination, but remain available to authorized
internal email rendering. Existing and automatic notices retain in_app=true. SQL
guards prove channel selection and forbid reads of email-only evidence.

This is explicit per-invitation/per-rule opt-in, without tenant-wide opt-in, implicit
email projection of fixed task/workflow notices, historical backfill, or new worker
identity. Configure email for supported task/workflow events through activated notify
rules under the existing delegated authority; their fixed in-app projections remain
unchanged. Core remains industry-neutral.

Migration adds a defaulted immutable visibility bit and partial inbox index without
rewriting retained IDs or evidence. Downgrade refuses while any email action version
or email-only notice exists; otherwise it restores the old channel guard and schema.
Use a forward fix or verified full restore for populated rollback. Test atomicity,
deduplication, all channel combinations, privacy, revocation, API/browser opt-in,
guarded migration and SMTP delivery through fake/loopback sinks only.
