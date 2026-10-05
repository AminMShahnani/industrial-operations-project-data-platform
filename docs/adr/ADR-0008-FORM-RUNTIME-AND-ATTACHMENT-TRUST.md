# ADR-0008: Governed form runtime and attachment trust

Status: Accepted
Date: 2026-10-05

## Decision
Use a bounded JSON expression AST with named field/context references, literals and
whitelisted functions/operators. Never parse Python/JS or execute customer code.
Analyze references and dependency cycles before publish. Use decimal text values,
UTC-aware datetime and stable component keys; enforce server validation on the
exact resolved version. Published snapshots and submitted revisions are immutable.
Reusable workspace libraries carry immutable numbered versions and explicit pins;
resolve references only inside the current tenant/workspace.

Form ownership is workspace with optional project scope. Explicit workspace
Owner/Admin and inherited OrganizationAdmin may manage workspace definitions.
ProjectManager manages project forms, Contributor creates own submissions and
Viewer reads published definitions. Drafts remain private to their owner; managers
may read submitted snapshots. Contributors cannot read other contributors' data.
Component permissions can restrict existing capability, never grant new access.
No implicit tenant access for platform operators. Terminal projects deny writes.

Attachments are quarantined in private object storage until a trusted scanner
returns clean. Scanner unavailable/failure rejects availability; no development
bypass. Validate sizes and byte signatures independently of client MIME/name.
Bound signed downloads to 60 seconds after fresh parent submission authorization.
Use a scanner application interface so deployment can supply its trusted scanner.
An uploaded file is owned by a draft and cannot be attached across scopes/owners.

A signature component in V1 records authenticated acknowledgement identity/time
and reason at submission, never a user-selected signer. Configurable signing
policies and legally qualified cryptographic signatures remain V1.5/enterprise
per docs/02; this reconciles the basic signature family in docs/09 without claiming
legal e-signature semantics. Previous-approved defaults resolve only approved
historical data when the workflow module supplies it; never treat submitted as
approved. Missing authoritative context remains unresolved and errors explicitly.

## Consequences
New behavior creates a new version. Draft save never mutates submitted history.
Publication/import has bounded validated contracts and preview before apply.
Files require operational scanner integration and isolated upload/security tests.
Domain Pack content stays declarative and industry-neutral in Core.

Immutable workspace libraries are shared builder inputs. An authorized project
form manager can read and pin libraries in that same workspace through the project
builder context, but cannot create/change workspace libraries without a workspace
form-management grant. Lookup users require exact email and effective form-read
access in the target scope; no unconstrained tenant directory is exposed. All lookup
lists are bounded and scope checked. A published form grants access only to names/IDs
of its configured master lookup type in its own scope, never unrelated record payloads.
The scanner adapter uses the [ClamD INSTREAM protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html)
with bounded requests, timeout and fail-closed responses. Deploy it on a trusted
private network; API clients cannot select scanner/storage endpoints. Actual request
bodies are bounded to 8 MiB before JSON parsing, including chunked bodies.

Current-date defaults use organization timezone; timestamps and signer evidence use
UTC. Read-only server values survive autosave, hidden responses are filtered and
private derived fields are recalculated internally. DefaultContext is a typed trusted
application port, with initialization errors until scheduling/workflow supply their
authoritative records. Failed DB writes remove only newly generated request-owned
object keys; inventory/reconciliation backstop is TD-005.
