param(
    [string]$OutputDir = "bin",
    [string]$BinaryName = "instrument-agent.exe",
    [string]$Version = "",
    [string]$Commit = "",
    [string]$BuildTime = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force $OutputDir | Out-Null

if (-not $Version) {
    if (Test-Path .git) {
        try {
            $Version = (git describe --tags --always) 2>$null
        } catch {
            $Version = "dev"
        }
    }
    if (-not $Version) { $Version = "dev" }
}
if (-not $Commit) {
    if (Test-Path .git) {
        try {
            $Commit = (git rev-parse --short HEAD) 2>$null
        } catch {
            $Commit = "unknown"
        }
    }
    if (-not $Commit) { $Commit = "unknown" }
}
if (-not $BuildTime) {
    $BuildTime = (Get-Date).ToUniversalTime().ToString("o")
}

$target = Join-Path $OutputDir $BinaryName
$ldflags = @(
    "-X instrument-connectivity/internal/buildinfo.Version=$Version",
    "-X instrument-connectivity/internal/buildinfo.Commit=$Commit",
    "-X instrument-connectivity/internal/buildinfo.BuildTime=$BuildTime"
) -join ' '

Write-Host "Building $target"
Write-Host "Version: $Version"
Write-Host "Commit: $Commit"
Write-Host "Build Time: $BuildTime"
go build -ldflags $ldflags -o $target .\cmd\agent

@{
    version = $Version
    commit = $Commit
    build_time = $BuildTime
    binary = $target
} | ConvertTo-Json -Depth 3 | Set-Content (Join-Path $OutputDir "build-metadata.json")

Write-Host "Built $target"
