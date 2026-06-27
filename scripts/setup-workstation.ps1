# SPDXLIMS Workstation Setup
# Run this ONCE on a new PC to install the SPDXLIMS desktop app.
#
# HOW TO GET THIS FILE ONTO THE NEW PC (pick one):
#   Option A — USB drive: copy this file to a USB drive, plug it in, right-click the
#              file and choose "Run with PowerShell".
#   Option B — Download it directly on the new PC: open PowerShell and run:
#              Invoke-WebRequest -Uri "https://raw.githubusercontent.com/gina108/spdxlims/main/scripts/setup-workstation.ps1" -OutFile "$env:USERPROFILE\Desktop\setup-workstation.ps1"
#              Then right-click the file on the Desktop and choose "Run with PowerShell".

$ErrorActionPreference = "Stop"

# Auto-elevate to Administrator (required for winget machine-scope installs)
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$InstallDir = "C:\SPDXLIMS"
$RepoUrl    = "https://github.com/gina108/spdxlims.git"
$Branch     = "main"

function Write-Step { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "    !! $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  SPDXLIMS Workstation Setup" -ForegroundColor White
Write-Host "  ===========================" -ForegroundColor White

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
Write-Step "Checking Python..."
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Warn "Python not found. Installing via winget (this may take a few minutes)..."
    winget install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements --silent
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        Write-Host "`n  Python install failed. Please install Python 3.11 from https://python.org then re-run this script." -ForegroundColor Red
        pause; exit 1
    }
}
$pythonExe = $pythonCmd.Source
Write-OK "Python: $pythonExe"

# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------
Write-Step "Checking Git..."
$gitExe = $null
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    $gitExe = $gitCmd.Source
} elseif (Test-Path "C:\Program Files\Git\cmd\git.exe") {
    $gitExe = "C:\Program Files\Git\cmd\git.exe"
}

if (-not $gitExe) {
    Write-Warn "Git not found. Installing via winget (this may take a few minutes)..."
    winget install --id Git.Git --source winget --accept-package-agreements --accept-source-agreements --silent
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
    $gitExe = "C:\Program Files\Git\cmd\git.exe"
    if (-not (Test-Path $gitExe)) {
        Write-Host "`n  Git install failed. Please install Git from https://git-scm.com then re-run this script." -ForegroundColor Red
        pause; exit 1
    }
}
Write-OK "Git: $gitExe"

# ---------------------------------------------------------------------------
# Clone or pull the repo
# ---------------------------------------------------------------------------
Write-Step "Setting up app files in $InstallDir..."
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Warn "$InstallDir already exists — pulling latest instead of cloning."
    & $gitExe -C $InstallDir pull
} else {
    & $gitExe clone --branch $Branch $RepoUrl $InstallDir
}
Write-OK "App files ready."

# ---------------------------------------------------------------------------
# Python virtual environment + dependencies
# ---------------------------------------------------------------------------
Write-Step "Setting up Python environment..."
$venvDir    = Join-Path $InstallDir ".venv"
$pipExe     = Join-Path $venvDir "Scripts\pip.exe"
$pythonwExe = Join-Path $venvDir "Scripts\pythonw.exe"

if (-not (Test-Path $venvDir)) {
    & $pythonExe -m venv $venvDir
}
& $pipExe install --quiet -r (Join-Path $InstallDir "requirements.txt")
Write-OK "Dependencies installed."

# ---------------------------------------------------------------------------
# Desktop shortcuts
# ---------------------------------------------------------------------------
Write-Step "Creating desktop shortcuts..."
$desktop   = [Environment]::GetFolderPath("Desktop")
$appPy     = Join-Path $InstallDir "app.py"
$updatePs1 = Join-Path $InstallDir "scripts\update-workstation.ps1"
$appIcon   = Join-Path $InstallDir "assets\SDX.ico"
$shell     = New-Object -ComObject WScript.Shell

$appLink = $shell.CreateShortcut((Join-Path $desktop "SPDXLIMS.lnk"))
$appLink.TargetPath       = $pythonwExe
$appLink.Arguments        = "`"$appPy`""
$appLink.WorkingDirectory = $InstallDir
$appLink.Description      = "SPDXLIMS Laboratory Information System"
if (Test-Path $appIcon) {
    $appLink.IconLocation = $appIcon
}
$appLink.Save()

$updateLink = $shell.CreateShortcut((Join-Path $desktop "Update SPDXLIMS.lnk"))
$updateLink.TargetPath       = "powershell.exe"
$updateLink.Arguments        = "-ExecutionPolicy Bypass -File `"$updatePs1`""
$updateLink.WorkingDirectory = $InstallDir
$updateLink.Description      = "Pull the latest SPDXLIMS update from GitHub"
$updateLink.Save()

Write-OK "Shortcuts created on Desktop."

Write-Host ""
Write-Host "  ================================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "  Open SPDXLIMS from the shortcut on your Desktop." -ForegroundColor Green
Write-Host "  To update later, use the 'Update SPDXLIMS' shortcut." -ForegroundColor Green
Write-Host "  ================================================" -ForegroundColor Green
Write-Host ""
pause
