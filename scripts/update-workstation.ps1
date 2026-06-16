# SPDXLIMS Workstation Update
# Pulls the latest version from GitHub and updates dependencies.
# A shortcut to this script is placed on the Desktop by setup-workstation.ps1.

$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot

function Write-Step { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "    OK: $msg" -ForegroundColor Green }

Write-Host ""
Write-Host "  SPDXLIMS Update" -ForegroundColor White
Write-Host "  ================" -ForegroundColor White

# ---------------------------------------------------------------------------
# Find Git
# ---------------------------------------------------------------------------
$gitExe = $null
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    $gitExe = $gitCmd.Source
} elseif (Test-Path "C:\Program Files\Git\cmd\git.exe") {
    $gitExe = "C:\Program Files\Git\cmd\git.exe"
}

if (-not $gitExe) {
    Write-Host "`n  Git not found. Run setup-workstation.ps1 first." -ForegroundColor Red
    pause; exit 1
}

# ---------------------------------------------------------------------------
# Pull latest code
# ---------------------------------------------------------------------------
Write-Step "Downloading latest version from GitHub..."
& $gitExe -C $AppDir pull
Write-OK "Code updated."

# ---------------------------------------------------------------------------
# Update dependencies (in case requirements.txt changed)
# ---------------------------------------------------------------------------
Write-Step "Checking dependencies..."
$pipExe = Join-Path $AppDir ".venv\Scripts\pip.exe"
if (-not (Test-Path $pipExe)) {
    Write-Host "`n  Virtual environment not found. Run setup-workstation.ps1 first." -ForegroundColor Red
    pause; exit 1
}
& $pipExe install --quiet -r (Join-Path $AppDir "requirements.txt")
Write-OK "Dependencies up to date."

Write-Host ""
Write-Host "  ================================================" -ForegroundColor Green
Write-Host "  Update complete!" -ForegroundColor Green
Write-Host "  Launch SPDXLIMS normally from your Desktop shortcut." -ForegroundColor Green
Write-Host "  ================================================" -ForegroundColor Green
Write-Host ""
pause
