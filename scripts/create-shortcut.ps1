$AppDir  = Split-Path -Parent $PSScriptRoot
$Python  = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
$Script  = Join-Path $AppDir "app.py"
$Desktop = [Environment]::GetFolderPath("Desktop")

if (-not (Test-Path $Python)) {
    Write-Host "pythonw.exe not found. Run setup first:" -ForegroundColor Red
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    pause
    exit 1
}

# Name and icon come from app_instance.json when this install has one, so the
# server checkout writes "SPDXLIMS Server.lnk" instead of overwriting the
# production install's "SPDXLIMS.lnk" on the same desktop.
$LinkName    = "SPDXLIMS"
$IconName    = "SDX.ico"
$Description = "SPDXLIMS Laboratory Information System"

$Marker = Join-Path $AppDir "app_instance.json"
if (Test-Path $Marker) {
    try {
        $instance = Get-Content $Marker -Raw | ConvertFrom-Json
        if ($instance.display_name) {
            $LinkName    = $instance.display_name
            $Description = "$($instance.display_name) Laboratory Information System"
        }
        if ($instance.icon) { $IconName = $instance.icon }
    } catch {
        Write-Warning "Could not read app_instance.json, falling back to defaults: $_"
    }
}

$Link = Join-Path $Desktop "$LinkName.lnk"
$Icon = Join-Path $AppDir "assets\$IconName"

# A shortcut stores a path to an icon, so it cannot follow this install's accent
# the way the running window does. The app leaves a turned copy here on a
# non-default accent; without it a blue install had a blue taskbar icon and a
# purple one on the desktop. Absent is normal on a purple install - the shipped
# asset is already right - and the app must have been started once to write it.
$AccentIcon = Join-Path $AppDir "data\app-icon.ico"
if (Test-Path $AccentIcon) {
    $Icon = $AccentIcon
}

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($Link)
$shortcut.TargetPath       = $Python
$shortcut.Arguments        = "`"$Script`""
$shortcut.WorkingDirectory = $AppDir
$shortcut.Description      = $Description
if (Test-Path $Icon) {
    $shortcut.IconLocation = $Icon
} else {
    Write-Warning "Icon not found: $Icon"
}
$shortcut.Save()

Write-Host "Shortcut created: $Link" -ForegroundColor Green
Write-Host "  target : $Python"
Write-Host "  icon   : $Icon"
