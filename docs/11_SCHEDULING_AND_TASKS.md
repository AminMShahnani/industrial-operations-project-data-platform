# Scheduling and Task Management

## Separation of concepts
Schedule = recurrence/trigger definition.
TaskOccurrence = concrete work item.
Submission = captured form data.

## Schedule types
one-time, daily/weekly/monthly, RRULE, shift-based, project-milestone based, relative to another event.

## Materialization
Use rolling horizon generation (e.g. next 30–60 days) plus periodic extension. Unique idempotency key: schedule/version + occurrence timestamp + assignment scope.

## Assignment targets
users, teams, departments, scoped roles, shifts. Resolve recipients using deterministic rules and retain assignment snapshot.

## Task states
open, in_progress, submitted, awaiting_review, returned, approved, overdue, cancelled, superseded.

## Inbox
Support personal, team, department and project views; due today, overdue, upcoming, returned and waiting review.

## Timezones
Schedule definitions include timezone. Persist normalized timestamps in UTC plus schedule timezone metadata.
