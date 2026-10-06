# Phase 4: scheduling and shared tasks

## Setup and authority
Apply `uv run alembic upgrade head`; Phase 4 head is b71acf0449b2. Start the existing
API/frontend and development infrastructure. Explicit workspace admins/owners,
project managers and inherited organization admins manage their scoped schedules.
Contributors execute assigned work. Assignment never grants workspace/project
permission. Platform operators have no implicit tenant operational access.

## Definitions and activation
Schedules belong to a workspace with optional project scope. Pin an exact published
form ID/number in the same scope. Save drafts with expected revision; preview
activation and apply its returned SHA-256 with unchanged revision. The reviewed
hash includes definition, exact form version and eligible recipient IDs. Changed
eligibility invalidates the preview. Active definitions are immutable.
Clone a higher numbered draft to change behavior. New activation pauses the previous
active version and supersedes only unclaimed future tasks; claimed/submitted/past
work retains its exact versions. Pause/resume/retire requires preview, revision and
reason. Pausing/retiring stops generation without deleting existing work/history.
Retired forms deny draft writes; deprecated forms do not create new task drafts.

The UI's My Work exposes schedule administration, properties, definition preview,
version history, activation/lifecycle and generation. Advanced JSON allows exact
user/group/shift targets, intervals/RRULEs, milestone/event pins and reminder offsets.
Server contracts are authoritative. Lists use cursor pagination.

```json
{"form_id":"EXACT_FORM_UUID","form_number":1,
 "recurrence":{"kind":"daily","timezone":"Asia/Tehran",
 "starts_local":"2026-10-06T08:00:00"},
 "assignments":[{"kind":"role","role":"ProjectManager"}],
 "due_after_seconds":28800,"reminder_offsets":[0,86400]}
```

User/team/department/shift targets use kind plus target_id; role targets use kind=role
and the effective scoped role preset, never provider claims. Active identities and
live execution permission are mandatory. Each assignment permits up to 1000 eligible
recipients; split larger work into explicit groups. Recipient snapshots are retained.

## Recurrence and bounded materialization
Kinds: one_time, interval, daily, weekly, monthly, rrule, shift, milestone,
relative_event. One-time/interval anchors (`at`) are offset-aware. Calendar/RRULE/
shift anchors (`starts_local`) are naive local wall times in the named IANA timezone.
Unknown zones, invalid anchors and inapplicable properties reject. Due durations and
fixed intervals are elapsed UTC seconds. Store UTC plus original timezone metadata.

RRULE profile: FREQ=DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT or UTC UNTIL,
plain weekday BYDAY, BYMONTHDAY (including negative days), BYMONTH and WKST=MO.
Unsupported parts, ordinal weekdays and sub-daily rule frequencies reject explicitly;
sub-daily elapsed recurrence uses interval kind (minimum 3600 seconds). Invalid dates
and nonexistent local times skip without consuming COUNT. Repeated wall times use
their first instant. Monthly day 31 never clamps into February.
See [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545#section-3.3.10) and ADR-0009
for the bounded profile; arbitrary iCalendar import is not supported.

Half-open windows are at most 60 days/2000 timestamps/2000 potential assignment work
items. Historical anchors are bounded to ten years. Generate/extend a rolling horizon.
Schedule locks and database uniqueness on tenant/version/timestamp/assignment scope
prevent duplicates under concurrency/retry. An empty live target generates no task
and can be retried after access correction; activation rejects empty targets.
Activation supersession is bounded to 2000 unclaimed future tasks. Larger replacements
require an explicit reviewed plan rather than an unbounded request.

## Shift, milestone and event inputs
POST /shifts creates an immutable numbered roster: code/name, timezone, local
starts_at, elapsed duration and eligible user_ids. Shift recurrence pins its UUID;
the recurrence date supplies the anchor and the roster supplies the local time.
Current-shift form defaults select the latest roster number per code in the exact
scope. Overlapping current rosters return unavailable context rather than guessing.
Industry terminology/content belongs to Domain Packs.
POST /milestones creates an immutable project-owned name/planned_at record. Pin its
UUID and optional elapsed offset_seconds. Changed plans create new records/versions.
POST /schedule-triggers records an audited code/occurred_at and idempotency_key.
Replays must match exact scope/content. Relative-event recurrence matches the code
in its exact scope and applies the bounded offset. Future integrations use the typed
application boundary; no customer executable code runs.

## Shared work, privacy and completion
My Work supports personal/team/department/project scopes and due today, overdue,
upcoming, returned and waiting-review filters. Today uses organization timezone;
task dates display schedule timezone. Overdue is a time-derived unfinished-work view.
Each assignment receives one shared task. Atomic claiming checks the original
recipient snapshot and fresh execution authority, then creates one private exact
form-version draft. Team/department/role actions recheck current membership/role.
Same claimant retries return that draft; competing claims conflict. New members
cannot silently claim old work. Peers cannot read the claimant's draft.
Open task form uses the existing runtime/autosave. Submission atomically preserves
its snapshot and moves its linked task to submitted. Submitted never means approved;
review/returned/approved contracts await Phase 5 trusted workflow authority.
Manager cancellation retains history and blocks linked draft writes. Reassignment
does not overwrite a claimant: cancel and issue explicitly governed replacement work.

## Periodic execution and reminders
Use a trusted deployment timer with a persisted tenant manager identity and configured
OIDC issuer; neither platform privilege nor arbitrary tenant IDs bypass permissions.
Preview first, then apply:

```powershell
uv run python scripts/scheduler_tick.py --organization ORG_UUID --workspace WS_UUID --project PROJECT_UUID --subject MANAGER_SUBJECT
uv run python scripts/scheduler_tick.py --organization ORG_UUID --workspace WS_UUID --project PROJECT_UUID --subject MANAGER_SUBJECT --apply
```

Default horizon 30 days (1-60 configurable). Run at least daily for extension and
more often for reminder timeliness. Each page commits atomically; failed ticks
retry without duplicate tasks/reminders. Commands fail visibly on revoked access.
Writes append immutable actor/request/correlation audit events. CLI reports counts.
In-app reminders are immutable once per task/offset: negative before due, positive
after due. Completed/cancelled tasks do not generate new reminders. UI generation and
per-task reads reauthorize scope/parent. Reminder is the typed durable Phase 6 delivery
handoff; email/queue delivery is not claimed in Phase 4. Previous-approved defaults
still require Phase 5 authoritative approval data.

## Migration and rollback
b71acf0449b2 adds milestones, shifts, triggers, schedules/versions, tasks, indexed
recipients and reminders. Composite foreign keys protect exact scope/version and
claimant/submission ownership. Triggers prohibit history deletion/truncation, active
definition edits, assignment rewrites and claim replacement. Task completion requires
its exact submitted snapshot. Empty roundtrip is tested; populated downgrade refuses
before removal. Retain schema while rolling back binaries, or restore a verified
backup into isolation and reconcile writes before cutover. Never delete history to
force rollback. No legacy export was supplied or migrated. Production backup/runtime
roles remain Phase 10 gates.

## Validation
Run scripts/check.ps1 with both isolated DB URLs and oidc-dev. Mandatory coverage:
DST/calendar bounds, isolation/access revocation, assignment snapshots, claim/privacy,
exact submission, reminders, shift/event/milestone inputs and paging. Real PKCE browser
checks include concurrent materialization and claim retries against separate API
transactions. Local and hosted gates must pass before acceptance or Phase 5.
