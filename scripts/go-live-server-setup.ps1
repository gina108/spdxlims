param(
    # Repo root. Defaults to this script's parent folder (scripts\ -> repo root).
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 8001,
    [string]$RemoteAddress = "10.0.0.0/24"
)

# Installs the SPDXLIMS backend as a Windows service and opens the firewall.
# RUN FROM AN ELEVATED (Administrator) POWERSHELL.

$ErrorActionPreference = "Stop"

# --- 0. Require elevation ---
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Not elevated. Re-open PowerShell with 'Run as administrator' and run this script again."
    return
}

$backend = Join-Path $Root "backend"
$py      = Join-Path $backend ".venv\Scripts\python.exe"
$svc     = "SPDXLIMSBackend"
$rule    = "SPDXLIMS Backend API"

if (-not (Test-Path $py))                          { throw "Backend venv python not found: $py" }
if (-not (Test-Path (Join-Path $backend ".env")))  { throw "backend\.env not found." }

Write-Host "1/5  Registering the pywin32 service host..." -ForegroundColor Cyan
& $py (Join-Path $backend ".venv\Scripts\pywin32_postinstall.py") -install -quiet | Out-Null

Write-Host "2/5  Installing the backend service (auto-start)..." -ForegroundColor Cyan
if (Get-Service -Name $svc -ErrorAction SilentlyContinue) {
    Write-Host "     Service already exists - skipping install."
} else {
    Push-Location $backend
    & $py service.py --startup auto install
    Pop-Location
}

Write-Host "3/5  Starting the service..." -ForegroundColor Cyan
Start-Service $svc
Start-Sleep -Seconds 6

Write-Host "4/5  Opening the firewall (TCP $Port, inbound, from $RemoteAddress only)..." -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -RemoteAddress $RemoteAddress -Profile Private | Out-Null

Write-Host "5/5  Verifying..." -ForegroundColor Cyan
Get-Service $svc | Format-List Name, Status, StartType
try {
    $h = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 10
    Write-Host ("Local health check: " + ($h | ConvertTo-Json -Compress)) -ForegroundColor Green
} catch {
    Write-Warning "Local health check failed: $_"
    Write-Warning "Check the service state above and the Windows Event Viewer (Application log) for details."
}

Write-Host ""
Write-Host "Done. From the SECOND computer, the server URL is:  http://10.0.0.10:$Port" -ForegroundColor Green
