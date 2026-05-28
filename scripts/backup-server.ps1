param(
    [string]$OutputDir = "backups",
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$AssetDir = "backend\app\static\uploads",
    [string]$PgBin = "",
    [string]$StatusPath = $env:BACKUP_STATUS_PATH
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$TargetDir = Join-Path $Root $OutputDir
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

$PgDump = if ($PgBin) { Join-Path $PgBin "pg_dump.exe" } else { "pg_dump" }

if (-not $DatabaseUrl) {
    throw "DATABASE_URL is required. Set it in the environment or pass -DatabaseUrl."
}
$ToolDatabaseUrl = $DatabaseUrl -replace '^postgresql\+psycopg2://', 'postgresql://' -replace '^postgresql\+psycopg://', 'postgresql://'

$DbBackup = Join-Path $TargetDir "spdxlims-db-$Timestamp.dump"
$AssetBackup = Join-Path $TargetDir "spdxlims-assets-$Timestamp.zip"

Write-Host "Backing up PostgreSQL database..."
& $PgDump --format=custom --file "$DbBackup" "$ToolDatabaseUrl"
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE."
}

$ResolvedAssetDir = Join-Path $Root $AssetDir
if (Test-Path $ResolvedAssetDir) {
    Write-Host "Backing up report assets..."
    Compress-Archive -Path (Join-Path $ResolvedAssetDir "*") -DestinationPath $AssetBackup -Force
} else {
    Write-Host "Asset directory not found; skipping asset backup: $ResolvedAssetDir"
}

Write-Host "Backup complete:"
Write-Host $DbBackup
if (Test-Path $AssetBackup) {
    Write-Host $AssetBackup
}

if ($StatusPath) {
    $StatusDir = Split-Path -Parent $StatusPath
    if ($StatusDir) {
        New-Item -ItemType Directory -Force -Path $StatusDir | Out-Null
    }
    @{
        status = "success"
        destination = (Resolve-Path $TargetDir).Path
        message = "Backup completed successfully."
        last_backup_at = (Get-Date).ToUniversalTime().ToString("o")
        database_backup = $DbBackup
        asset_backup = if (Test-Path $AssetBackup) { $AssetBackup } else { "" }
    } | ConvertTo-Json -Depth 4 | Set-Content -Path $StatusPath -Encoding UTF8
}
