param(
    [string]$BinaryPath = ".\bin\instrument-agent.exe",
    [string]$ServiceName = "InstrumentConnectivityEngine"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$binary = Resolve-Path $BinaryPath
& $binary -uninstall-service -service-name $ServiceName
Write-Host "Service uninstall command completed for $ServiceName"
