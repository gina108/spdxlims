param(
    # Install root holding data\ and the venv. Defaults to this script's parent.
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [double]$Interval = 30,
    [switch]$Uninstall
)

# Installs the headless instrument importer as an always-on task.
# RUN FROM AN ELEVATED (Administrator) POWERSHELL.
#
# The engine service is always on, but until this existed the only thing moving
# its captures into Postgres was a timer inside the desktop app - so closing the
# app on the main PC stopped the second workstation seeing new analyzer results.
#
# Runs as SYSTEM at startup, like the backend task, for the same reason: a
# pywin32 service is unreliable inside a virtualenv.
#
# This belongs ONLY on the PC wired to the analyzers. The engine binds loopback,
# so a workstation cannot reach it; the importer refuses to start there anyway.

$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Not elevated. Re-open PowerShell with 'Run as administrator' and run this again."
    return
}

$taskName = "SPDXLIMSInstrumentImporter"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask  -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed $taskName." -ForegroundColor Green
    } else {
        Write-Host "$taskName was not installed."
    }
    return
}

$py = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { throw "venv pythonw not found: $py" }

$deployment = Join-Path $Root "data\deployment.json"
if (-not (Test-Path $deployment)) { throw "data\deployment.json not found under $Root." }
if ((Get-Content $deployment -Raw | ConvertFrom-Json).mode -ne "server") {
    throw "Deployment mode is not 'server'. In local mode the desktop app imports directly and this task is not needed."
}

Write-Host "1/3  Registering $taskName (runs as SYSTEM)..." -ForegroundColor Cyan
$action    = New-ScheduledTaskAction -Execute $py `
                 -Argument "-m spdxlims.instrument_importer --root `"$Root`" --interval $Interval" `
                 -WorkingDirectory $Root
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                 -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
                 -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "2/3  Starting..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 6

Write-Host "3/3  Checking the heartbeat..." -ForegroundColor Cyan
$beat = Join-Path $Root "data\instrument-importer.heartbeat"
if (Test-Path $beat) {
    Write-Host ("Importer running. Heartbeat: " + (Get-Content $beat -Raw).Trim()) -ForegroundColor Green
} else {
    Write-Warning "No heartbeat yet. Check data\logs\spdxlims.log, or run it in the foreground:"
    Write-Warning "  cd `"$Root`"; .\.venv\Scripts\python.exe -m spdxlims.instrument_importer --once"
}
