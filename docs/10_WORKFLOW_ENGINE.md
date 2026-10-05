# Workflow Engine

## Purpose
Model review/approval without hardcoding `submitted/approved/rejected` into each form.

## Definition
WorkflowDefinition -> WorkflowVersion -> Nodes + Transitions.
Node types V1: start, review, approval, decision, notify, end.

## Assignment strategies
specific user, project role, department role, team, submission field reference, manager-of relation where supported.

## Runtime
Submission starts a WorkflowInstance referencing immutable WorkflowVersion. Each action creates WorkflowAction records and immutable audit events.

## Behavior
- reject can return to configured node or submitter;
- resubmission preserves history;
- escalation may be timer-based;
- approval policy may require one, all, quorum or sequential approvers;
- final closure locks governed fields unless a correction/amendment process is used.

## Amendments
Changing an approved record creates an amendment/revision, not an invisible overwrite.
