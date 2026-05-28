param(
    [int]$Port = 8001,
    [string]$RemoteAddress = "LocalSubnet",
    [string]$RuleName = "SPDXLIMS Backend API"
)

$ErrorActionPreference = "Stop"

$Existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($Existing) {
    Set-NetFirewallRule -DisplayName $RuleName -Enabled True
    Set-NetFirewallPortFilter -AssociatedNetFirewallRule $Existing -Protocol TCP -LocalPort $Port
    Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $Existing -RemoteAddress $RemoteAddress
    Write-Host "Firewall rule updated: $RuleName"
    exit 0
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress $RemoteAddress `
    -Profile Private

Write-Host "Firewall rule created: $RuleName"
Write-Host "RemoteAddress: $RemoteAddress"
