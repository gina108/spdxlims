# Launch the development instrument engine (server-version testing).
#
# Runs in the console, NOT as a Windows service, so it is off unless you start it
# and can never fight the production engine for the analyzers.
#
#   Production : C:\SPDXLIMS, Windows service, port 9088, owns the hardware.
#   Development: this repo,    console only,    port 9089, replay only.
#
# -no-auto-resume is the important flag. Session resume is driven by engine.db, not
# by the `enabled:` field in the profile YAML, so without it this engine would
# reopen whatever profiles were live when the DB was last written - seizing COM6,
# the COR50 listener on 5101 and the Mindray monitor on 2575 out from under
# production, and consuming CM250 drop files before the real lab ever sees them.
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path $PSScriptRoot -Parent
$Exe      = Join-Path $RepoRoot 'instrument-connectivity\bin\instrument-agent.exe'
$DataDir  = Join-Path $RepoRoot 'data\instrument-engine'

if (-not (Test-Path $Exe)) {
    throw "Engine binary not found: $Exe`nBuild it with instrument-connectivity\scripts\build-release.ps1"
}

# Refuse to start if production is not where it should be - otherwise this engine
# and the service are still sharing one data directory.
$svc = Get-CimInstance Win32_Service -Filter "Name='InstrumentConnectivityEngine'" -ErrorAction SilentlyContinue
if ($svc -and $svc.PathName -like "*$RepoRoot*") {
    Write-Warning "The production service is STILL running from this repo:"
    Write-Warning "  $($svc.PathName)"
    Write-Warning "Run split-engine.ps1 first, or dev and prod will share one database."
    if ((Read-Host "Start anyway? (y/N)") -ne 'y') { return }
}

Write-Host "Dev engine  : http://127.0.0.1:9089" -ForegroundColor Green
Write-Host "Data dir    : $DataDir"
Write-Host "Auto-resume : DISABLED" -ForegroundColor Green
Write-Host ""
Write-Host "Do NOT start a live capture from this engine's UI while the lab is running -" -ForegroundColor Yellow
Write-Host "the analyzers can only be owned by one process. Use POST /api/replay instead." -ForegroundColor Yellow
Write-Host ""

& $Exe -data-dir $DataDir -listen 127.0.0.1:9089 -no-auto-resume
