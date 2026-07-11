param(
    # Repo root. Defaults to this script's parent folder (scripts\ -> repo root).
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 8001,
    [string]$RemoteAddress = "10.0.0.0/24"
)

# Runs the SPDXLIMS backend as an always-on task and opens the firewall.
# RUN FROM AN ELEVATED (Administrator) POWERSHELL.
#
# Uses a Scheduled Task (SYSTEM, at startup) rather than a pywin32 Windows
# service: pythonservice.exe is unreliable inside a virtualenv, whereas a task
# launching the venv python directly is robust and also survives reboots.

$ErrorActionPreference = "Stop"

# --- 0. Require elevation ---
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Not elevated. Re-open PowerShell with 'Run as administrator' and run this script again."
    return
}

$backend = Join-Path $Root "backend"
$py      = Join-Path $backend ".venv\Scripts\python.exe"
$taskName = "SPDXLIMSBackend"
$rule    = "SPDXLIMS Backend API"

if (-not (Test-Path $py))                          { throw "Backend venv python not found: $py" }
if (-not (Test-Path (Join-Path $backend ".env")))  { throw "backend\.env not found." }

Write-Host "1/5  Removing any previous (broken) pywin32 service..." -ForegroundColor Cyan
if (Get-Service -Name $taskName -ErrorAction SilentlyContinue) {
    & sc.exe stop $taskName  | Out-Null
    Start-Sleep -Seconds 2
    & sc.exe delete $taskName | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "     Old service removed."
} else {
    Write-Host "     No previous service."
}

Write-Host "2/5  Registering the backend as a startup task (runs as SYSTEM)..." -ForegroundColor Cyan
$action    = New-ScheduledTaskAction -Execute $py -Argument "-m uvicorn app.main:app --host 0.0.0.0 --port $Port" -WorkingDirectory $backend
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                 -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
                 -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "3/5  Starting the backend now..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 8

Write-Host "4/5  Opening the firewall (TCP $Port, inbound, from $RemoteAddress only)..." -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -RemoteAddress $RemoteAddress -Profile Private | Out-Null

Write-Host "5/5  Verifying..." -ForegroundColor Cyan
(Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo) | Format-List TaskName, LastRunTime, LastTaskResult
try {
    $h = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 10
    Write-Host ("Local health check: " + ($h | ConvertTo-Json -Compress)) -ForegroundColor Green
    Write-Host ""
    Write-Host "SUCCESS. From the SECOND computer, the server URL is:  http://10.0.0.10:$Port" -ForegroundColor Green
} catch {
    Write-Warning "Local health check failed: $_"
    Write-Warning "Run this to see the error directly:  cd `"$backend`"; & `"$py`" -m uvicorn app.main:app --host 0.0.0.0 --port $Port"
}
