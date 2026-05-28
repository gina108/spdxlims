param(
    [string]$BinaryPath = ".\bin\instrument-agent.exe",
    [string]$DataDir = ".runtime",
    [string]$Listen = "127.0.0.1:9088",
    [string]$ServiceName = "InstrumentConnectivityEngine",
    [string]$DisplayName = "Instrument Connectivity Engine",
    [string]$Description = "Clinical LIS instrument connectivity runtime",
    [int]$RetentionDays = 30,
    [int]$SessionEventMax = 5000,
    [int]$RuntimeErrorMax = 2000,
    [int]$CaptureMax = 2000,
    [string]$CleanupInterval = "6h",
    [string]$ApiToken = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$binary = Resolve-Path $BinaryPath
$args = @(
    "-install-service",
    "-service-name", $ServiceName,
    "-service-display-name", $DisplayName,
    "-service-description", $Description,
    "-data-dir", $DataDir,
    "-listen", $Listen,
    "-retention-days", $RetentionDays,
    "-session-event-max", $SessionEventMax,
    "-runtime-error-max", $RuntimeErrorMax,
    "-capture-max", $CaptureMax,
    "-cleanup-interval", $CleanupInterval
)
if ($ApiToken) {
    $args += @("-api-token", $ApiToken)
}
& $binary @args
Write-Host "Service install command completed for $ServiceName"
