# Master Data

## Purpose
Prevent uncontrolled free-text duplication and give forms consistent references.

## Core registries
Users, departments, teams, projects, locations, units, currencies, shifts.

## Domain registries
Provided by packs, e.g. rig, well, field, bit type, mud type, equipment class, NPT code.

## Model
MasterDataType defines schema and governance. MasterDataRecord stores typed values, code, name, status, validity dates and metadata.

## Scope
Records may be global reference, organization, workspace or project scoped. Pack seeds may be copied/materialized with provenance.

## Lifecycle
active, inactive, deprecated. Referenced records are not hard-deleted.

## Import/export
CSV/XLSX import with validation, duplicate detection and dry run. Export supports stable IDs/codes.
