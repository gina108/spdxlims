param(
    [string]$OutputRoot = "dist",
    [string]$PackageName = "instrument-connectivity-windows",
    [string]$BinaryName = "instrument-agent.exe",
    [string]$Version = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Version) {
    if (Test-Path .git) {
        try {
            $Version = (git describe --tags --always) 2>$null
        } catch {
            $Version = "dev"
        }
    }
    if (-not $Version) { $Version = "dev" }
}

$packageRoot = Join-Path $OutputRoot $PackageName
$buildDir = Join-Path $OutputRoot "build"
$binDir = Join-Path $packageRoot "bin"
$webDir = Join-Path $packageRoot "web"
$profilesDir = Join-Path $packageRoot "profiles"
$scriptsDir = Join-Path $packageRoot "scripts"
$docsDir = Join-Path $packageRoot "docs"
$runtimeDir = Join-Path $packageRoot "runtime-data"

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build-release.ps1") -OutputDir $buildDir -BinaryName $BinaryName -Version $Version
}

$builtBinary = Join-Path $buildDir $BinaryName
$buildMetadataPath = Join-Path $buildDir "build-metadata.json"
if (-not (Test-Path $builtBinary)) {
    throw "Built binary not found at $builtBinary"
}
if (-not (Test-Path $buildMetadataPath)) {
    throw "Build metadata not found at $buildMetadataPath"
}
$buildMetadata = Get-Content $buildMetadataPath | ConvertFrom-Json

if (Test-Path $packageRoot) {
    Remove-Item -Recurse -Force $packageRoot
}

New-Item -ItemType Directory -Force $binDir, $webDir, $profilesDir, $scriptsDir, $docsDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $runtimeDir "incoming"), (Join-Path $runtimeDir "captures"), (Join-Path $runtimeDir "support-bundles"), (Join-Path $runtimeDir "profiles") | Out-Null

Copy-Item $builtBinary (Join-Path $binDir $BinaryName)
Copy-Item $buildMetadataPath (Join-Path $packageRoot "build-metadata.json")
Copy-Item .\web\* $webDir -Recurse
Copy-Item .\profiles\* $profilesDir -Recurse
Copy-Item .\scripts\install-service.ps1 $scriptsDir
Copy-Item .\scripts\uninstall-service.ps1 $scriptsDir
Copy-Item .\README.md $packageRoot
Copy-Item .\docs\ARCHITECTURE.md $docsDir
Copy-Item .\docs\WINDOWS_DEPLOYMENT.md $docsDir
Copy-Item .\docs\UPGRADE.md $docsDir

$packageReadme = @(
    '# Instrument Connectivity Engine Windows Package',
    '',
    "Version: $($buildMetadata.version)",
    "Commit: $($buildMetadata.commit)",
    "Build Time: $($buildMetadata.build_time)",
    '',
    'Contents:',
    '- `bin\instrument-agent.exe`: main runtime binary',
    '- `web\`: local admin UI assets',
    '- `profiles\`: seed analyzer/interface profiles',
    '- `scripts\`: service install and uninstall helpers',
    '- `runtime-data\`: default runtime working directory',
    '- `docs\`: architecture, deployment, and upgrade notes',
    '',
    'Quick start:',
    '1. Open PowerShell as Administrator.',
    '2. From this package folder, install the service:',
    '',
    '```powershell',
    'pwsh .\scripts\install-service.ps1 -BinaryPath .\bin\instrument-agent.exe -DataDir .\runtime-data',
    '```',
    '',
    '3. Open `http://127.0.0.1:9088`.',
    '',
    'Console run without service:',
    '',
    '```powershell',
    '.\bin\instrument-agent.exe -data-dir .\runtime-data',
    '.\bin\instrument-agent.exe -version',
    '```'
)
$packageReadme | Set-Content (Join-Path $packageRoot "PACKAGE_README.md")

$manifest = @{
    package_name = $PackageName
    version = $buildMetadata.version
    commit = $buildMetadata.commit
    build_time = $buildMetadata.build_time
    built_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    binary = "bin/$BinaryName"
    runtime_data = "runtime-data"
    web = "web"
    profiles = @(
        "profiles/generic-hl7.yaml",
        "profiles/generic-astm.yaml",
        "profiles/generic-csv-filedrop.yaml"
    )
    scripts = @(
        "scripts/install-service.ps1",
        "scripts/uninstall-service.ps1"
    )
    docs = @(
        "docs/ARCHITECTURE.md",
        "docs/WINDOWS_DEPLOYMENT.md",
        "docs/UPGRADE.md"
    )
    upgrade_marker = @{
        current_version = $buildMetadata.version
        previous_version = ""
        migration_required = $false
        notes_file = "docs/UPGRADE.md"
    }
} | ConvertTo-Json -Depth 6
$manifest | Set-Content (Join-Path $packageRoot "package-manifest.json")

$zipBase = "$PackageName-$($buildMetadata.version)"
$zipPath = Join-Path $OutputRoot ($zipBase + ".zip")
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}
Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $zipPath
Write-Host "Packaged release folder: $packageRoot"
Write-Host "Packaged release zip: $zipPath"
