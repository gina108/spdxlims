# SPDXLIMS Server Update Workflow

This is the practical update path for the current deployment shape: this computer builds an update package, the server applies it, and production data stays on the server.

## One-Time Server Setup

1. Install PostgreSQL and configure `backend\.env` on the server using `docs\PRODUCTION_DEPLOYMENT.md`.
2. Install the backend service:

```powershell
cd C:\SPDXLIMS
.\scripts\install-backend-service.ps1 -Port 8001
.\scripts\configure-backend-firewall.ps1 -Port 8001 -RemoteAddress LocalSubnet
```

3. Confirm the server backend is reachable from this computer:

```powershell
Invoke-WebRequest http://SERVER_NAME_OR_IP:8001/health -UseBasicParsing
```

4. In the desktop app on each workstation, use Settings to select Server Mode and set the server URL to `http://SERVER_NAME_OR_IP:8001`.

## Updating The Server

On this computer, after making code changes:

```powershell
cd C:\SPDXLIMS
.\scripts\new-server-update-package.ps1
```

The script runs the project checks, stages source files, excludes local data/secrets/build output, and creates a zip under `outputs\server-updates`.

Copy the newest zip to the server, for example to:

```text
C:\SPDXLIMS\incoming-updates
```

On the server, apply it:

```powershell
cd C:\SPDXLIMS
.\scripts\apply-server-update.ps1 `
  -PackagePath "C:\SPDXLIMS\incoming-updates\spdxlims-server-update-YYYYMMDD-HHMMSS.zip" `
  -DatabaseUrl "postgresql+psycopg://spdxlims_app:CHANGE_ME_DB_PASSWORD@localhost:5432/spdxlims_prod" `
  -PgBin "C:\Progra~1\PostgreSQL\18\bin"
```

The apply script:

- backs up the PostgreSQL database and uploaded assets
- stops the `SPDXLIMSBackend` service
- copies the update into `C:\SPDXLIMS`
- preserves server-only files such as `backend\.env`, `data`, `backups`, and `.venv`
- installs backend dependencies
- runs Alembic migrations
- restarts the backend service
- checks `http://127.0.0.1:8001/health`

## Fast Patch Option

For a code-only patch where the database schema and dependencies did not change, you can skip those steps:

```powershell
.\scripts\apply-server-update.ps1 `
  -PackagePath "C:\SPDXLIMS\incoming-updates\spdxlims-server-update-YYYYMMDD-HHMMSS.zip" `
  -DatabaseUrl "postgresql+psycopg://spdxlims_app:CHANGE_ME_DB_PASSWORD@localhost:5432/spdxlims_prod" `
  -PgBin "C:\Progra~1\PostgreSQL\18\bin" `
  -SkipDependencyInstall `
  -SkipMigrations
```

Keep the backup step on unless you have already taken a known-good backup.

## Rollback

If an update fails after the backup is created:

1. Stop the backend service.
2. Restore the latest database and assets with `scripts\restore-server.ps1`.
3. Re-apply the previous known-good update package if code files were already copied.
4. Start the backend service and check `/health`.

## Recommended Next Improvement

Once the server is stable, put `C:\SPDXLIMS` under a private Git repository. Then the server update flow can become `git pull`, dependency install, migrations, restart, and smoke test. The package workflow is intentionally conservative because this folder is not currently a Git checkout.
