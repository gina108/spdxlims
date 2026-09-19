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

# Note what the heartbeat says before we touch anything, so the check at the
# end can prove the NEW process is writing it rather than just finding the old
# file lying there.
$beat = Join-Path $Root "data\instrument-importer.heartbeat"
$before = if (Test-Path $beat) { (Get-Content $beat -Raw).Trim() } else { "" }

# A running task must be stopped first. Scheduled tasks default to
# MultipleInstances=IgnoreNew, so Start-ScheduledTask is silently a no-op while
# an old instance is alive - re-registering alone would leave stale code running.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "0/3  Stopping the running importer..." -ForegroundColor Cyan
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if ((Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue).State -ne "Running") { break }
    }
    if ((Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue).State -eq "Running") {
        Write-Warning "     Task is still Running after 20s; the new code may not load."
    } else {
        Write-Host "     Stopped."
    }
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

# The heartbeat must ADVANCE. Merely existing proves nothing: a stopped task
# leaves its last one behind, which once made a failed restart look like a
# success while stale code kept running.
Write-Host "3/3  Waiting for a fresh heartbeat..." -ForegroundColor Cyan
$fresh = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $beat) {
        $now = (Get-Content $beat -Raw).Trim()
        if ($now -and $now -ne $before) { $fresh = $true; break }
    }
}

if ($fresh) {
    Write-Host ("Importer running. Heartbeat: " + (Get-Content $beat -Raw).Trim()) -ForegroundColor Green
} else {
    Write-Warning "The heartbeat did not advance - the importer may not have started."
    Write-Warning "Check data\logs\spdxlims.log, or run it in the foreground to see the error:"
    Write-Warning "  cd `"$Root`"; .\.venv\Scripts\python.exe -m spdxlims.instrument_importer --once"
}
