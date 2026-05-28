param(
    [string]$SqlitePath = "data\spdxlims.db",
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$PythonExe = ".\backend\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $DatabaseUrl) {
    throw "DatabaseUrl is required. Pass -DatabaseUrl or set DATABASE_URL."
}
if (-not (Test-Path $SqlitePath)) {
    throw "SQLite database not found: $SqlitePath"
}

& $PythonExe backend\scripts\verify_migration.py --sqlite $SqlitePath --database-url $DatabaseUrl --allow-extra-users
if ($LASTEXITCODE -ne 0) {
    throw "Migration verification failed with exit code $LASTEXITCODE."
}
