param(
    [string]$ServiceName = "SPDXLIMSBackend",
    [string]$DisplayName = "SPDXLIMS Backend API",
    [string]$ProjectRoot = "C:\SPDXLIMS",
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"

$BackendRoot = Join-Path $ProjectRoot "backend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw "Backend Python executable not found: $PythonExe"
}
if (-not (Test-Path (Join-Path $BackendRoot ".env"))) {
    throw "Production .env not found. Copy backend\.env.production.example to backend\.env and fill it before installing the service."
}

$Command = "`"$PythonExe`" -m uvicorn app.main:app --app-dir `"$BackendRoot`" --host 0.0.0.0 --port $Port"
$Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Existing) {
    throw "Service already exists: $ServiceName. Use scripts\uninstall-backend-service.ps1 first if you need to reinstall it."
}

New-Service `
    -Name $ServiceName `
    -DisplayName $DisplayName `
    -BinaryPathName $Command `
    -StartupType Automatic `
    -Description "Runs the SPDXLIMS FastAPI backend."

Write-Host "Service installed: $ServiceName"
Write-Host "The service command uses --app-dir so it does not depend on the Windows service working directory."
