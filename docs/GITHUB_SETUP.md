# SPDXLIMS GitHub Setup

Use a private GitHub repository as the source of truth for the program. Keep production data and secrets only on the server.

## This Computer

After GitHub CLI is installed, log in from a normal PowerShell window:

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" auth login --hostname github.com --git-protocol https --web
```

Set the Git commit email to the email connected to your GitHub account:

```powershell
cd C:\SPDXLIMS
git config user.name "Regina Cunningham"
git config user.email "YOUR_GITHUB_EMAIL"
```

Create the first commit:

```powershell
cd C:\SPDXLIMS
git add .
git commit -m "Initial SPDXLIMS source"
```

Create a private GitHub repo and push:

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" repo create spdxlims --private --source . --remote origin --push
```

After that, the normal development flow is:

```powershell
cd C:\SPDXLIMS
.\scripts\check.ps1
git add .
git commit -m "Describe the change"
git push
```

## Server

Clone the private repo onto the server:

```powershell
cd C:\
git clone https://github.com/YOUR_GITHUB_USERNAME/spdxlims.git SPDXLIMS
```

Then create the server-only files that are not stored in Git:

- `backend\.env`
- `backend\.venv`
- PostgreSQL database
- uploaded assets and backups

Install the backend service using `docs\PRODUCTION_DEPLOYMENT.md`.

## Updating The Server

Once the server is cloned from GitHub, update it with:

```powershell
cd C:\SPDXLIMS
.\scripts\update-server-from-git.ps1 `
  -DatabaseUrl "postgresql+psycopg://spdxlims_app:CHANGE_ME_DB_PASSWORD@localhost:5432/spdxlims_prod" `
  -PgBin "C:\Progra~1\PostgreSQL\18\bin"
```

The script fetches the latest private GitHub code, backs up production data, stops the backend service, pulls the new commit, installs dependencies, runs migrations, restarts the service, and checks backend health.

## Never Commit

These are intentionally ignored by `.gitignore`:

- `backend\.env`
- `.venv` and `backend\.venv`
- `data`
- `backups`
- `outputs`
- local spreadsheet exports
- generated reports, labels, logs, captures, and build artifacts
