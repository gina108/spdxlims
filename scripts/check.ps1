param(
    [switch]$SkipBackendTests,
    [switch]$SkipGoTests,
    [switch]$SkipCompile,
    [switch]$RunBackendIntegration
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
}

Set-Location $Root
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

if (-not $SkipCompile) {
    Invoke-Step "Compile Python packages" {
        & $Python -m compileall app.py spdxlims backend\app backend\scripts
    }
}

if (-not $SkipBackendTests) {
    Invoke-Step "Run Python tests" {
        if ($RunBackendIntegration) {
            $env:RUN_BACKEND_INTEGRATION = "1"
        }
        & $Python -m pytest
    }
}

if (-not $SkipGoTests) {
    Invoke-Step "Run instrument connectivity tests" {
        Push-Location instrument-connectivity
        try {
            go test ./...
        } finally {
            Pop-Location
        }
    }
}

Write-Host ""
Write-Host "All requested checks completed." -ForegroundColor Green
