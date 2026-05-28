# Server Migration Checklist

This codebase currently runs as a desktop app that opens a local SQLite file directly. To support a server plus at least three workstations, we need to move shared workflows behind the backend API and PostgreSQL.

## Phase 1: Foundation

- [x] Add desktop deployment settings separate from the lab settings stored in SQLite
- [x] Add server health check from the desktop UI
- [x] Add a first backend API area for desktop workflows (`patients`)
- [ ] Add desktop API client/service layer for shared entities
- [ ] Add desktop login/session handling for API auth
- [ ] Add environment-specific server URL configuration for each workstation

Files to change first:
- [spdxlims/app.py](/C:/SPDXLIMS/spdxlims/app.py)
- [spdxlims/main_window.py](/C:/SPDXLIMS/spdxlims/main_window.py)
- [spdxlims/pages/settings_page.py](/C:/SPDXLIMS/spdxlims/pages/settings_page.py)
- [spdxlims/server_client.py](/C:/SPDXLIMS/spdxlims/server_client.py)
- [spdxlims/deployment.py](/C:/SPDXLIMS/spdxlims/deployment.py)

## Phase 2: First Shared Workflow Rewrite

Rewrite `patients` first because it is the smallest core workflow and is used from multiple places.

Desktop modules to rewrite first:
- [spdxlims/pages/patients_page.py](/C:/SPDXLIMS/spdxlims/pages/patients_page.py)
- [spdxlims/pages/orders_page.py](/C:/SPDXLIMS/spdxlims/pages/orders_page.py) for `PatientDialog`

Backend modules to build/expand first:
- [backend/app/models/models.py](/C:/SPDXLIMS/backend/app/models/models.py)
- [backend/app/routers/patients.py](/C:/SPDXLIMS/backend/app/routers/patients.py)
- [backend/app/routers/__init__.py](/C:/SPDXLIMS/backend/app/routers/__init__.py)
- [backend/alembic/versions](/C:/SPDXLIMS/backend/alembic/versions)

Patient workflow requirements:
- list patients with active/archived filtering
- get patient details
- create patient
- update patient
- archive/unarchive patient

## Phase 3: Order Entry Rewrite

Rewrite orders next because they drive labels, results, reports, billing, and instrument routing.

Desktop modules:
- [spdxlims/pages/orders_page.py](/C:/SPDXLIMS/spdxlims/pages/orders_page.py)

Backend capabilities needed:
- lab order endpoints
- doctor endpoints
- client endpoints
- label and preallocation support

## Phase 4: Results and Reports Rewrite

Desktop modules:
- [spdxlims/pages/results_page.py](/C:/SPDXLIMS/spdxlims/pages/results_page.py)
- [spdxlims/pages/reports_page.py](/C:/SPDXLIMS/spdxlims/pages/reports_page.py)

Backend capabilities needed:
- order result entry
- validation/finalization
- report preview/final snapshot generation
- shared asset access for logos/header/footer/signature files

## Phase 5: Catalog and Admin Rewrite

Desktop modules:
- [spdxlims/pages/tests_page.py](/C:/SPDXLIMS/spdxlims/pages/tests_page.py)
- [spdxlims/pages/catalog_page.py](/C:/SPDXLIMS/spdxlims/pages/catalog_page.py)
- [spdxlims/pages/administrative_page.py](/C:/SPDXLIMS/spdxlims/pages/administrative_page.py)
- [spdxlims/pages/equipment_page.py](/C:/SPDXLIMS/spdxlims/pages/equipment_page.py)

## Cross-Cutting Changes Still Required

- move local asset/file handling to server-backed storage
- add user login/logout and token refresh
- add data migration from SQLite to PostgreSQL
- add workstation/server install documentation
- add backup/restore procedures
- add multi-user conflict handling and audit coverage

## Definition of Done

The migration is complete when:
- workstations no longer open `data/spdxlims.db` for shared workflows
- the server owns shared data in PostgreSQL
- all three workstations can create/update records against the same backend
- instruments submit data to server-side services instead of local workstation state
