# Form Engine

## Goals
Dynamic yet governed forms, suitable for operational reporting and reusable domain templates.

## Form structure
Form -> Version -> Sections -> Components.
Supported V1 component families:
text, textarea, integer, decimal, boolean, date, datetime, time, select, multi-select, radio, user, department, project, master-data lookup, file/image, signature, calculated value, table/repeating group, display/instruction.

## Component contract
Each component has stable `key`, type, label, required flag, validation schema, permissions, presentation metadata, default expression, visibility condition and optional data source.

## Reusable libraries
- FieldDefinition: atomic semantic field.
- ComponentTemplate: reusable group/section.
- FormTemplate: full form starter.

References should support pinning to a version. Publishing resolves references into an immutable executable definition/snapshot.

## Conditional logic
Use a safe declarative expression language. Conditions can control visibility, requiredness, validation and workflow/automation context. No eval.

## Formula engine
Safe expression AST with whitelisted operators/functions. Formula dependencies are analyzed for cycles before publication.

## Defaults
Static, current user/date/project/shift, master-data lookup, previous approved submission, and derived expressions.

## Validation
Client validates for UX; server validates authoritatively against the exact FormVersion.

## Publication lifecycle
Draft -> Validation -> Published -> Deprecated/Retired. Published definitions are immutable.
