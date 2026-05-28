param(
    [Parameter(Mandatory = $true)]
    [string]$DbBackup,
    [string]$AssetBackup = "",
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$AssetDir = "backend\app\static\uploads",
    [string]$PgBin = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$PgRestore = if ($PgBin) { Join-Path $PgBin "pg_restore.exe" } else { "pg_restore" }

if (-not $DatabaseUrl) {
    throw "DATABASE_URL is required. Set it in the environment or pass -DatabaseUrl."
}
$ToolDatabaseUrl = $DatabaseUrl -replace '^postgresql\+psycopg2://', 'postgresql://' -replace '^postgresql\+psycopg://', 'postgresql://'
if (-not (Test-Path $DbBackup)) {
    throw "Database backup not found: $DbBackup"
}

Write-Host "Restoring PostgreSQL database..."
& $PgRestore --clean --if-exists --no-owner --dbname "$ToolDatabaseUrl" "$DbBackup"
if ($LASTEXITCODE -ne 0) {
    throw "pg_restore failed with exit code $LASTEXITCODE."
}

if ($AssetBackup) {
    if (-not (Test-Path $AssetBackup)) {
        throw "Asset backup not found: $AssetBackup"
    }
    $ResolvedAssetDir = Join-Path $Root $AssetDir
    New-Item -ItemType Directory -Force -Path $ResolvedAssetDir | Out-Null
    Write-Host "Restoring report assets..."
    Expand-Archive -Path $AssetBackup -DestinationPath $ResolvedAssetDir -Force
}

Write-Host "Restore complete."
