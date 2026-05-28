param(
    [string]$ServiceName = "SPDXLIMSBackend"
)

$ErrorActionPreference = "Stop"

$Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $Service) {
    Write-Host "Service not found: $ServiceName"
    exit 0
}

if ($Service.Status -ne "Stopped") {
    Stop-Service -Name $ServiceName -Force
}

sc.exe delete $ServiceName | Out-Host
Write-Host "Service removed: $ServiceName"
