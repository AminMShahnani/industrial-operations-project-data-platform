# Oil & Gas Starter Domain Pack

## Initial focus
Drilling and daily operations reporting. This pack is an accelerator, not a hard-coded industry mode.

## Suggested master data
field, well, wellbore, rig, contractor, company, shift, hole section, operation code, NPT category, equipment, bit type, BHA component type, mud system, incident category, units.

## Initial templates
- Daily Drilling Report
- Daily Operations Report
- Mud Report
- BHA Report
- Bit Report
- NPT Report
- HSE/Incident Report
- Equipment Inspection
- Maintenance Report
- Material Consumption
- Personnel/Shift Report
- Daily Cost Report
- Shift Handover

## Workflow presets
Operator-only review, supervisor approval, operator+client sequential approval, HSE incident escalation.

## Automation examples
- NPT above threshold -> notify manager + create NPT investigation task.
- overdue daily report -> escalation.
- high-severity HSE incident -> create investigation workflow.

## Dashboards
submission completion, overdue reports, ROP trend, NPT hours/category, approval delay, safety incident summary, equipment downtime.

## Standards mapping direction
Provide mapping adapters/profiles for commonly used drilling reporting and well-data standards where useful. Keep standard-specific schemas out of Core.
