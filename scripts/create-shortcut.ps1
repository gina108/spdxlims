$AppDir  = Split-Path -Parent $PSScriptRoot
$Python  = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
$Script  = Join-Path $AppDir "app.py"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Link    = Join-Path $Desktop "SPDXLIMS.lnk"

if (-not (Test-Path $Python)) {
    Write-Host "pythonw.exe not found. Run setup first:" -ForegroundColor Red
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    pause
    exit 1
}

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($Link)
$shortcut.TargetPath       = $Python
$shortcut.Arguments        = "`"$Script`""
$shortcut.WorkingDirectory = $AppDir
$shortcut.Description      = "SPDXLIMS Laboratory Information System"
$shortcut.Save()

Write-Host "Shortcut created: $Link" -ForegroundColor Green
