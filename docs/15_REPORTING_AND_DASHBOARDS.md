# Reporting and Dashboards

## Principles
Operational writes stay normalized/governed; reporting reads use query models/materialized views where needed.

## Standard views
- completion rate by project/form/department
- overdue tasks
- approval turnaround
- rejected/returned submissions
- project lifecycle progress
- domain KPIs shipped by packs

## Report builder
V1 supports selected data source, filters, columns, sorting, grouping and saved report definitions. Advanced joins are curated rather than arbitrary SQL.

## Dashboard widgets
metric, trend, bar/line, table, status distribution, overdue list. Each widget references a governed reporting dataset.

## Exports
CSV/XLSX/PDF. Large exports are background jobs with access checks at generation and download time.

## Historical correctness
Reports must honor versioned definitions and timestamps; changing a current label must not silently rewrite historical measurements where semantic meaning changed.
