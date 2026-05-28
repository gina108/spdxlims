param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDatabaseUrl,
    [Parameter(Mandatory = $true)]
    [string]$RestoreDatabaseUrl,
    [string]$OutputDir = "backups\restore-drills",
    [string]$AssetDir = "backend\app\static\uploads",
    [string]$PgBin = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($SourceDatabaseUrl -eq $RestoreDatabaseUrl) {
    throw "SourceDatabaseUrl and RestoreDatabaseUrl must be different. Never rehearse restore into production."
}

if ($PgBin) {
    $env:PATH = "$PgBin;$env:PATH"
}
$Psql = if ($PgBin) { Join-Path $PgBin "psql.exe" } else { "psql" }
$ToolRestoreDatabaseUrl = $RestoreDatabaseUrl -replace '^postgresql\+psycopg2://', 'postgresql://' -replace '^postgresql\+psycopg://', 'postgresql://'

Write-Host "Creating rehearsal backup from source database..."
& .\scripts\backup-server.ps1 -DatabaseUrl $SourceDatabaseUrl -OutputDir $OutputDir -AssetDir $AssetDir -PgBin $PgBin

$LatestDbBackup = Get-ChildItem (Join-Path $Root $OutputDir) -Filter "spdxlims-db-*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $LatestDbBackup) {
    throw "No database backup was created."
}

$LatestAssetBackup = Get-ChildItem (Join-Path $Root $OutputDir) -Filter "spdxlims-assets-*.zip" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

Write-Host "Restoring latest backup into rehearsal database..."
if ($null -ne $LatestAssetBackup) {
    & .\scripts\restore-server.ps1 -DatabaseUrl $RestoreDatabaseUrl -DbBackup $LatestDbBackup.FullName -AssetBackup $LatestAssetBackup.FullName -AssetDir $AssetDir -PgBin $PgBin
} else {
    & .\scripts\restore-server.ps1 -DatabaseUrl $RestoreDatabaseUrl -DbBackup $LatestDbBackup.FullName -AssetDir $AssetDir -PgBin $PgBin
}

Write-Host "Verifying restored core table counts..."
$VerifySql = "select 'app_user' as table_name, count(*) from app_user union all select 'patient', count(*) from patient union all select 'lab_order', count(*) from lab_order union all select 'result', count(*) from result union all select 'report_snapshot', count(*) from report_snapshot;"
& $Psql $ToolRestoreDatabaseUrl -c $VerifySql
if ($LASTEXITCODE -ne 0) {
    throw "Restore verification query failed with exit code $LASTEXITCODE."
}

Write-Host "Restore rehearsal completed successfully."
