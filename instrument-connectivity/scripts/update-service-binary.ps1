param(
    [string]$ServiceName = "InstrumentConnectivityEngine",
    [string]$Binary = (Join-Path (Split-Path -Parent $PSScriptRoot) "bin\instrument-agent.exe"),
    [int]$Port = 9088
)

# Swaps the engine binary the Windows service runs and starts it again.
# The service holds the .exe open, so it has to stop for the copy - analyzers
# cannot connect during that window, which is a few seconds.
# RUN FROM AN ELEVATED (Administrator) PowerShell.

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Not elevated. Re-open PowerShell with 'Run as administrator' and run this again."
    return
}
if (-not (Test-Path $Binary)) {
    throw "Built binary not found: $Binary. Run scripts\build-release.ps1 first."
}

$service = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if (-not $service) { throw "Service not found: $ServiceName" }

# The service command line carries its arguments, so the target is the first
# quoted or unquoted path in it rather than a hardcoded location.
$target = ($service.PathName -replace '^"([^"]+)".*$', '$1') -replace '^([^\s]+)\s.*$', '$1'
Write-Host "Service binary: $target" -ForegroundColor Cyan

$backup = "$target.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
Copy-Item $target $backup
Write-Host "Backed up to  : $backup" -ForegroundColor Cyan

Write-Host "Stopping $ServiceName..." -ForegroundColor Cyan
Stop-Service -Name $ServiceName -Force
(Get-Service $ServiceName).WaitForStatus('Stopped', '00:00:30')

try {
    Copy-Item $Binary $target -Force
    Write-Host "Copied new binary." -ForegroundColor Green
} catch {
    Write-Warning "Copy failed ($_). Restoring the previous binary."
    Copy-Item $backup $target -Force
} finally {
    Write-Host "Starting $ServiceName..." -ForegroundColor Cyan
    Start-Service -Name $ServiceName
    (Get-Service $ServiceName).WaitForStatus('Running', '00:00:30')
}

Start-Sleep -Seconds 2
try {
    $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 10
    Write-Host ("Engine healthy: " + ($health | ConvertTo-Json -Compress)) -ForegroundColor Green
} catch {
    Write-Warning "Health check failed: $_"
    Write-Warning "The previous binary is at $backup if you need to put it back."
}
