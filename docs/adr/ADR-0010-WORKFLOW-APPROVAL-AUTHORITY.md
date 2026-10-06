# ADR-0010: Workflow approval authority

Status: Accepted; user selected the recommended rule on 2026-10-06
Date: 2026-10-06

## Context
docs/10 requires configurable approval assignments and one/all/quorum/sequential
policies, immutable workflow versions, action history and governed amendments.
It does not specify whether a submitter may approve their own record. This is an
authorization boundary, not an implementation detail. AGENTS.md requires resolving
security-sensitive ambiguity before implementing dependent behavior.

## Decision
Require independent approval: a submission's author cannot approve that record.
Assignment resolution must not silently substitute administrators when an eligible
independent approver is unavailable. Persisted assignments never replace fresh
server-side permission checks. The alternative is explicitly configured self-approval
in a workflow definition; it requires an affirmative product decision.

User instructed "do it" in response to the independent-approval recommendation.
Q-005 is resolved. Independent approval is mandatory, including for administrators;
the workflow definition cannot opt out. Reviews do not constitute final approval.

## Required implementation invariants
Core remains industry-neutral. Instances pin immutable workflow versions and
submitted snapshots. Every action records the authenticated actor, time, reason
and immutable audit event. Returns, resubmissions and amendments retain original
payloads and evidence; no approved or submitted record is overwritten.
Cross-module integration uses application contracts, not unrelated table access.
No new execution framework or arbitrary user-authored code is introduced.

## Graph and policy implementation
The initial typed profile bounds definitions to 100 nodes and 200 transitions.
There is exactly one start; every node is reachable and every forward path ends.
Decision nodes have explicit true/false branches. Forward cycles are rejected;
human nodes declare separate return targets (submitter or another human node).
Return/resubmission history will use distinct persisted visits, preserving original
actions rather than rewriting a completed visit. Sequential assignments preserve
resolution order; repeated identities cannot contribute multiple quorum votes.
An empty independent-approver set fails closed. Unsupported manager relationships
must report unavailable assignment context instead of fabricating a manager.

Workflow definitions own their persistence. Composite scope keys pin form versions;
activated content and identity cannot change. Populated downgrade refuses before
any table drop. These are foundation invariants, not a claim that runtime actions,
amendments or workflow APIs have passed Phase 5 acceptance.
