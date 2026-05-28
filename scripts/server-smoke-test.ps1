param(
    [string]$DatabaseUrl = $env:TEST_DATABASE_URL,
    [string]$PythonExe = ".\backend\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $DatabaseUrl) {
    throw "DatabaseUrl is required. Pass -DatabaseUrl or set TEST_DATABASE_URL. Use a disposable database because this test drops and recreates tables."
}

$env:RUN_BACKEND_INTEGRATION = "1"
$env:TEST_DATABASE_URL = $DatabaseUrl

& $PythonExe -m pytest backend\tests\test_api_integration.py
