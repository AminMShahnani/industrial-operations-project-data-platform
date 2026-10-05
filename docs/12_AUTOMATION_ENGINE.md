# Automation Engine

## Model
Trigger -> Conditions -> Actions.

## Triggers V1
submission.created/submitted/approved/rejected
workflow.step.entered/completed
task.created/due/overdue
project.phase.changed
master_data.changed
scheduled timer
integration event

## Conditions
Declarative safe expressions over event context and permitted lookups.

## Actions
create task, create form task, send notification, start workflow, set controlled metadata, create related record, call webhook, append tag/flag.

## Guarantees
- each rule version is immutable after activation;
- every run has correlation ID, status, attempts, timestamps and outputs;
- action execution must be idempotent;
- retry with backoff for transient failures;
- dead-letter failed runs;
- no arbitrary code execution.

## Safety
Actions that could materially alter governance require elevated permission and explicit audit. Domain Packs may ship inactive automation templates; organization admins activate them.
