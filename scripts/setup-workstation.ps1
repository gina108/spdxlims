# SPDXLIMS Workstation Setup
# Run this ONCE on a new PC to install the SPDXLIMS desktop app.
#
# HOW TO GET THIS FILE ONTO THE NEW PC (pick one):
#   Option A - USB drive: copy this file to a USB drive, plug it in, right-click the
#              file and choose "Run with PowerShell".
#   Option B - Download it directly on the new PC: open PowerShell and run:
#              Invoke-WebRequest -Uri "https://raw.githubusercontent.com/gina108/spdxlims/main/scripts/setup-workstation.ps1" -OutFile "$env:USERPROFILE\Desktop\setup-workstation.ps1"
#              Then right-click the file on the Desktop and choose "Run with PowerShell".

$ErrorActionPreference = "Stop"

# Auto-elevate to Administrator (required for winget machine-scope installs)
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

# Never let the (elevated) window vanish on an error before it can be read: catch
# any terminating error, print it, and wait for the user instead of closing.
trap {
    Write-Host "`n  SETUP FAILED:" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ScriptStackTrace) { Write-Host "`n  $($_.ScriptStackTrace)" -ForegroundColor DarkGray }
    Read-Host "`n  Press Enter to close"
    exit 1
}

$InstallDir = "C:\SPDXLIMS"
$RepoUrl    = "https://github.com/gina108/spdxlims.git"
$Branch     = "main"

function Write-Step { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "    !! $msg" -ForegroundColor Yellow }

function Find-RealPython {
    # Returns a path to a WORKING python, skipping the Windows Store alias stub
    # (under \WindowsApps\, which only opens the Store and breaks venv/pip). Tries
    # the py launcher, PATH, and the standard winget install locations.
    $candidates = @(
        (Get-Command py     -ErrorAction SilentlyContinue).Source,
        (Get-Command python -ErrorAction SilentlyContinue).Source,
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and ($c -notlike "*\WindowsApps\*") -and (Test-Path $c)) {
            try { $null = & $c --version 2>&1; if ($LASTEXITCODE -eq 0) { return $c } } catch { }
        }
    }
    return $null
}

Write-Host ""
Write-Host "  SPDXLIMS Workstation Setup" -ForegroundColor White
Write-Host "  ===========================" -ForegroundColor White

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
Write-Step "Checking Python..."
$pythonExe = Find-RealPython
if (-not $pythonExe) {
    Write-Warn "Python not found. Installing via winget (this may take a few minutes)..."
    winget install --id Python.Python.3.11 --source winget --scope machine --accept-package-agreements --accept-source-agreements --silent
    # winget updates the persisted PATH, not this process's; refresh it so we can
    # find the freshly installed python without needing a new window.
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
    $pythonExe = Find-RealPython
    if (-not $pythonExe) {
        Write-Warn "Python was installed but this window can't see it yet."
        Write-Host "  Please CLOSE this window and run setup-workstation.ps1 again." -ForegroundColor Yellow
        Write-Host "  It will detect Python and continue the rest of the setup." -ForegroundColor Yellow
        Read-Host "`n  Press Enter to close"
        exit 1
    }
}
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
    Write-Warn "$InstallDir already exists - pulling latest instead of cloning."
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
