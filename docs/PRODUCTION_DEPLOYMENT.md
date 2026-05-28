# SPDXLIMS Production Deployment Runbook

Use this checklist before moving a lab workstation from local SQLite mode to shared server mode.

## 1. Production Environment

1. Install PostgreSQL on the server.
2. Create a dedicated database and user, for example:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d postgres -c "CREATE USER spdxlims_app WITH PASSWORD 'CHANGE_ME_DB_PASSWORD';"
& "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U postgres -O spdxlims_app spdxlims_prod
```

3. Copy `backend\.env.production.example` to `backend\.env`.
4. Replace every `CHANGE_ME` value in `backend\.env`.
5. Generate a strong `JWT_SECRET_KEY`:

```powershell
-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | ForEach-Object {[char]$_})
```

6. Install backend dependencies:

```powershell
cd C:\SPDXLIMS\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

7. Apply database migrations and seed the first admin:

```powershell
cd C:\SPDXLIMS\backend
.\.venv\Scripts\alembic.exe upgrade head
$env:APP_ENV = "production"
$env:SEED_ADMIN_EMAIL = "admin@spdxlims.local"
$env:SEED_ADMIN_PASSWORD = "CHANGE_ME_ADMIN_PASSWORD"
.\.venv\Scripts\python.exe scripts\seed.py
```

8. Start the backend:

```powershell
cd C:\SPDXLIMS\backend
.\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8001
```

For client deployment, install it as a managed process instead of leaving it in a terminal:

```powershell
cd C:\SPDXLIMS
.\scripts\install-backend-service.ps1 -Port 8001
.\scripts\configure-backend-firewall.ps1 -Port 8001 -RemoteAddress LocalSubnet
```

If the built-in Windows service cannot set the working directory correctly on the target machine, use Task Scheduler or NSSM with:

- Program: `C:\SPDXLIMS\backend\.venv\Scripts\python.exe`
- Arguments: `-m uvicorn app.main:app --host 0.0.0.0 --port 8001`
- Start in: `C:\SPDXLIMS\backend`

## 2. Production-Like Smoke Test

Run this against a disposable database before using the real production database:

```powershell
cd C:\SPDXLIMS
.\scripts\server-smoke-test.ps1 -DatabaseUrl "postgresql+psycopg://spdxlims_test:SdxTest123!@localhost:5432/spdxlims_test"
```

The smoke test drops and recreates all tables in the target database. Never point it at production.

After the backend is running, also do one manual desktop smoke test:

1. Open SPDXLIMS desktop.
2. Go to Settings.
3. Select Server Mode.
4. Set Server URL to `http://SERVER_NAME_OR_IP:8001`.
5. Log in as the seeded admin.
6. Create a patient, order, result, and finalized report.
7. Confirm Settings shows server session and backup status.

## 3. Backup And Restore Rehearsal

Run a backup from the source database and restore it into a separate rehearsal database:

```powershell
cd C:\SPDXLIMS
.\scripts\rehearse-restore.ps1 `
  -SourceDatabaseUrl "postgresql+psycopg://spdxlims_app:CHANGE_ME_DB_PASSWORD@localhost:5432/spdxlims_prod" `
  -RestoreDatabaseUrl "postgresql+psycopg://spdxlims_restore:CHANGE_ME_RESTORE_PASSWORD@localhost:5432/spdxlims_restore" `
  -PgBin "C:\Progra~1\PostgreSQL\18\bin"
```

Use the `PgBin` folder that matches the running PostgreSQL server version. `C:\Progra~1\PostgreSQL\18\bin` is the space-safe form of `C:\Program Files\PostgreSQL\18\bin`.

The source and restore database URLs must be different. Restores use `pg_restore --no-owner` so a rehearsal database can be owned by a different PostgreSQL role than the source database. A successful rehearsal proves that `pg_dump`, `pg_restore`, assets, and the restored database verification path all work.
The rehearsal verifies restored table counts without running the destructive smoke test against the restored database.

## 4. Migration Checklist

Before the cutover:

- Confirm `.\scripts\check.ps1` passes.
- Confirm `.\scripts\server-smoke-test.ps1` passes against disposable PostgreSQL.
- Confirm a restore rehearsal passes.
- Confirm the real server has `backend\.env` with production values.
- Confirm the desktop can log in to the backend from every workstation that will use it.
- Confirm firewall allows TCP `8001` only from trusted workstations or a reverse proxy.
- Confirm seeded/admin passwords have been replaced with client-owned credentials.
- Confirm backups write to a durable destination outside the app folder.
- Confirm someone can restore from backup without using production as the target.

Cutover:

1. Stop desktop writes during final migration.
2. Back up `data\spdxlims.db`.
3. Import SQLite data into the production database:

```powershell
cd C:\SPDXLIMS\backend
.\.venv\Scripts\python.exe scripts\import_sqlite.py --sqlite ..\data\spdxlims.db
```

4. Start the backend.
5. Switch one desktop to Server Mode and verify patients, catalog, orders, results, providers, and reports.
6. Switch remaining desktops to Server Mode.

## 5. Hosting Shape

Pick one before deployment:

- Office Windows server: simplest LAN setup, easiest printer/instrument access, requires local backup discipline.
- Cloud VM: easier offsite access and snapshots, requires HTTPS/VPN and stronger firewall rules.
- Existing NAS or mini PC: workable for small labs if Windows service reliability and backup storage are clear.

For the current app, the most conservative first deployment is an office Windows server on the LAN, with PostgreSQL and the FastAPI backend running on the same machine.

## 6. Data Migration Dry Run

Before the final cutover, import the current SQLite database into a staging PostgreSQL database:

```powershell
cd C:\SPDXLIMS\backend
$env:DATABASE_URL = "postgresql+psycopg://spdxlims_stage:CHANGE_ME_STAGE_PASSWORD@localhost:5432/spdxlims_stage"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\import_sqlite.py --sqlite ..\data\spdxlims.db
```

Then compare counts in the desktop and server for patients, providers, tests, panels, orders, results, and report snapshots. Resolve differences before production cutover.

Use the verification wrapper for the count comparison:

```powershell
cd C:\SPDXLIMS
.\scripts\verify-migration.ps1 `
  -SqlitePath "data\spdxlims.db" `
  -DatabaseUrl "postgresql+psycopg://spdxlims_stage:CHANGE_ME_STAGE_PASSWORD@localhost:5432/spdxlims_stage"
```

The verifier compares patients, doctors, clients, tests, reference ranges, panels, orders, order items, results, report snapshots, and report items.
