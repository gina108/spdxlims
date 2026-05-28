param(
    [string]$ProjectRoot = "C:\SPDXLIMS",
    [string]$ServiceName = "SPDXLIMSBackend",
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$PgBin = "",
    [int]$Port = 8001,
    [string]$Branch = "main",
    [switch]$SkipBackup,
    [switch]$SkipDependencyInstall,
    [switch]$SkipMigrations
)

$ErrorActionPreference = "Stop"
$BackendRoot = Join-Path $ProjectRoot "backend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
}

if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
    throw "Project root is not a Git repository: $ProjectRoot"
}
if (-not (Test-Path $PythonExe)) {
    throw "Backend Python executable not found: $PythonExe"
}
if (-not (Test-Path (Join-Path $BackendRoot ".env"))) {
    throw "Server backend .env not found. Production secrets must stay on the server."
}

Set-Location $ProjectRoot

Invoke-Step "Fetch latest source" {
    git fetch origin
}

Invoke-Step "Show pending update" {
    git log --oneline --decorate --max-count=10 HEAD..origin/$Branch
}

if (-not $SkipBackup) {
    Invoke-Step "Back up server before update" {
        & (Join-Path $ProjectRoot "scripts\backup-server.ps1") -DatabaseUrl $DatabaseUrl -PgBin $PgBin
    }
}

Invoke-Step "Stop backend service" {
    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($Service -and $Service.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force
        $Service.WaitForStatus("Stopped", "00:00:30")
    }
}

try {
    Invoke-Step "Apply latest source" {
        git checkout $Branch
        git pull --ff-only origin $Branch
    }

    if (-not $SkipDependencyInstall) {
        Invoke-Step "Install backend dependencies" {
            & $PythonExe -m pip install -r (Join-Path $BackendRoot "requirements.txt")
        }
    }

    if (-not $SkipMigrations) {
        Invoke-Step "Apply database migrations" {
            Push-Location $BackendRoot
            try {
                if ($DatabaseUrl) {
                    $env:DATABASE_URL = $DatabaseUrl
                }
                & (Join-Path $BackendRoot ".venv\Scripts\alembic.exe") upgrade head
            } finally {
                Pop-Location
            }
        }
    }
} catch {
    Write-Host ""
    Write-Host "Update failed. The backend service will be started again with the current files." -ForegroundColor Yellow
    throw
} finally {
    Invoke-Step "Start backend service" {
        Start-Service -Name $ServiceName
    }
}

Invoke-Step "Check backend health" {
    $HealthUrl = "http://127.0.0.1:$Port/health"
    $Response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 15
    if ($Response.StatusCode -lt 200 -or $Response.StatusCode -ge 300) {
        throw "Backend health check failed with status $($Response.StatusCode)."
    }
    Write-Host "Backend healthy at $HealthUrl"
}

Write-Host ""
Write-Host "Git-based server update complete." -ForegroundColor Green
