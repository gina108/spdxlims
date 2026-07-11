param([int]$Port = 8001)

# Restarts the SPDXLIMS backend so it loads updated code.
# RUN FROM AN ELEVATED (Administrator) PowerShell.

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Not elevated. Re-open PowerShell with 'Run as administrator' and run this again."
    return
}

$task = "SPDXLIMSBackend"

Write-Host "Stopping backend..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Free the port in case the old worker lingers.
$pid8001 = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($pid8001) { Stop-Process -Id $pid8001 -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1 }

Write-Host "Starting backend..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $task
Start-Sleep -Seconds 7

try {
    $h = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 10
    Write-Host ("Backend healthy: " + ($h | ConvertTo-Json -Compress)) -ForegroundColor Green
} catch {
    Write-Warning "Health check failed: $_"
}
