param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$ProjectRoot = "C:\SPDXLIMS",
    [string]$ServiceName = "SPDXLIMSBackend",
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$PgBin = "",
    [int]$Port = 8001,
    [switch]$SkipBackup,
    [switch]$SkipDependencyInstall,
    [switch]$SkipMigrations
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$TempRoot = Join-Path $env:TEMP ("spdxlims-apply-update-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
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

if (-not (Test-Path $PackagePath)) {
    throw "Update package not found: $PackagePath"
}
if (-not (Test-Path $ProjectRoot)) {
    throw "Project root not found: $ProjectRoot"
}
if (-not (Test-Path $PythonExe)) {
    throw "Backend Python executable not found: $PythonExe"
}
if (-not (Test-Path (Join-Path $BackendRoot ".env"))) {
    throw "Server backend .env not found. The update will not create or replace production secrets."
}

Set-Location $ProjectRoot

if (-not $SkipBackup) {
    Invoke-Step "Back up server before update" {
        $BackupScript = Join-Path $ProjectRoot "scripts\backup-server.ps1"
        if (-not (Test-Path $BackupScript)) {
            throw "Backup script not found: $BackupScript"
        }
        & $BackupScript -DatabaseUrl $DatabaseUrl -PgBin $PgBin
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
    Invoke-Step "Unpack update package" {
        if (Test-Path $TempRoot) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
        Expand-Archive -Path $PackagePath -DestinationPath $TempRoot -Force
    }

    Invoke-Step "Copy update into project folder" {
        $RoboArgs = @(
            $TempRoot,
            $ProjectRoot,
            "/E",
            "/R:2",
            "/W:2",
            "/XD",
            ".venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            "data",
            "backups",
            "outputs",
            "/XF",
            ".env",
            "*.pyc",
            "*.pyo",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "*.log"
        )
        & robocopy @RoboArgs
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy failed with exit code $LASTEXITCODE."
        }
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
} finally {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}

Invoke-Step "Start backend service" {
    Start-Service -Name $ServiceName
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
Write-Host "Server update complete." -ForegroundColor Green
