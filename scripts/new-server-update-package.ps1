param(
    [string]$OutputDir = "outputs\server-updates",
    [string]$Version = "",
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$PackageVersion = if ($Version) { $Version } else { $Timestamp }
$TargetDir = Join-Path $Root $OutputDir
$StagingDir = Join-Path $env:TEMP "spdxlims-update-$PackageVersion"
$PackagePath = Join-Path $TargetDir "spdxlims-server-update-$PackageVersion.zip"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
}

function Copy-ProjectItem {
    param(
        [string]$RelativePath
    )

    $Source = Join-Path $Root $RelativePath
    $Destination = Join-Path $StagingDir $RelativePath
    if (-not (Test-Path $Source)) {
        return
    }

    $Parent = Split-Path -Parent $Destination
    if ($Parent) {
        New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    }

    if ((Get-Item $Source).PSIsContainer) {
        Copy-Item -Path $Source -Destination $Destination -Recurse -Force
    } else {
        Copy-Item -Path $Source -Destination $Destination -Force
    }
}

Set-Location $Root

if (-not $SkipChecks) {
    Invoke-Step "Run pre-package checks" {
        & (Join-Path $Root "scripts\check.ps1")
    }
}

if (Test-Path $StagingDir) {
    Remove-Item -LiteralPath $StagingDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

Invoke-Step "Stage source files" {
    @(
        "app.py",
        "requirements.txt",
        "README.md",
        "SERVER_MIGRATION_CHECKLIST.md",
        "docker-compose.yml",
        "backend",
        "docs",
        "scripts",
        "spdxlims",
        "assets",
        "sample_addons",
        "instrument-connectivity\cmd",
        "instrument-connectivity\docs",
        "instrument-connectivity\fixtures",
        "instrument-connectivity\internal",
        "instrument-connectivity\profiles",
        "instrument-connectivity\scripts",
        "instrument-connectivity\web",
        "instrument-connectivity\go.mod",
        "instrument-connectivity\README.md",
        "niimbot-helper\cmd",
        "niimbot-helper\internal",
        "niimbot-helper\scripts",
        "niimbot-helper\go.mod",
        "niimbot-helper\README.md"
    ) | ForEach-Object { Copy-ProjectItem $_ }
}

Invoke-Step "Build instrument connectivity package" {
    Push-Location (Join-Path $Root "instrument-connectivity")
    try {
        & (Join-Path $Root "instrument-connectivity\scripts\package-release.ps1") -OutputRoot $StagingDir -PackageName "instrument-connectivity-windows" -Version $PackageVersion
    } finally {
        Pop-Location
    }

    Get-ChildItem -Path $StagingDir -Filter "instrument-connectivity-windows-*.zip" -File |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}

Invoke-Step "Remove local-only files from package" {
    @(
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "backend\.venv",
        "backend\.env",
        "backend\staged-smoke.stdout.log",
        "backend\staged-smoke.stderr.log",
        "backend\backup-status.json"
    ) | ForEach-Object {
        $Path = Join-Path $StagingDir $_
        if (Test-Path $Path) {
            Remove-Item -LiteralPath $Path -Recurse -Force
        }
    }

    Get-ChildItem -Path $StagingDir -Recurse -Directory -Force |
        Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", "dist", "build") } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

    Get-ChildItem -Path $StagingDir -Recurse -File -Force |
        Where-Object { $_.Extension -in @(".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".log") } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}

Invoke-Step "Create update package" {
    if (Test-Path $PackagePath) {
        Remove-Item -LiteralPath $PackagePath -Force
    }
    Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $PackagePath -Force
}

Remove-Item -LiteralPath $StagingDir -Recurse -Force

Write-Host ""
Write-Host "Update package ready:" -ForegroundColor Green
Write-Host $PackagePath
