# SPDXLIMS Operations Priorities

This document tracks the operational improvements needed before a multi-workstation production rollout.

## Server Migration

The desktop app should stop opening shared workflow data directly from `data/spdxlims.db`. Shared entities should move behind the FastAPI backend and PostgreSQL in this order:

1. Patients
2. Orders, doctors, clients, labels
3. Results and report snapshots
4. Catalog, pricing, inventory, billing, and admin workflows

Each rewritten workflow should include desktop API calls, backend tests, audit events, and a migration path from the existing SQLite data.

## Audit Coverage

Audit logging should be required for clinically or financially important changes:

- patient create/update/archive/unarchive
- order create/update/cancel/status changes
- result entry, edit, verification, amendment
- report finalization and amendment
- test catalog/reference range changes
- pricing, invoice, payment, and month-close actions
- inventory lot and stock movement actions
- instrument result ingestion and mapping overrides
- SQLite import and server migration actions

Audit records should include actor, action, entity, entity id, before/after payloads when safe, and timestamp.

## Backup And Restore

Before production, add a documented backup and restore workflow for:

- PostgreSQL database
- uploaded/shared report assets
- instrument connectivity profiles and confirmed runtime links
- application configuration excluding secrets

Recommended user-facing checks:

- last successful backup time
- backup destination
- restore drill date
- clear warning when backups have never completed

Initial scripts are available:

- `scripts/backup-server.ps1`
- `scripts/restore-server.ps1`
- `scripts/rehearse-restore.ps1`
- `scripts/server-smoke-test.ps1`
- `scripts/verify-migration.ps1`

Both expect `DATABASE_URL` to point at the production PostgreSQL database, or you can pass `-DatabaseUrl`. Run a restore drill against a non-production database before trusting any backup process.

See `docs/PRODUCTION_DEPLOYMENT.md` for the current deployment runbook.

## Runtime Data Hygiene

Generated PDFs, labels, captures, logs, local databases, support bundles, and build outputs should live outside source control. The repository should stay focused on source files, migrations, fixtures, scripts, and documentation.
