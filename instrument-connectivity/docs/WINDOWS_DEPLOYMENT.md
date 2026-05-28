# Windows Deployment

## Goal
Package the Instrument Connectivity Engine as a Windows-friendly local service that can be copied to a workstation or instrument interface PC and installed with minimal manual setup.

## Release Layout
The packaged release contains:
- `bin\instrument-agent.exe`
- `build-metadata.json`
- `web\`
- `profiles\`
- `scripts\install-service.ps1`
- `scripts\uninstall-service.ps1`
- `runtime-data\`
- `docs\ARCHITECTURE.md`
- `docs\WINDOWS_DEPLOYMENT.md`
- `docs\UPGRADE.md`
- `PACKAGE_README.md`
- `package-manifest.json`

## Build A Package
From the repo root:

```powershell
pwsh .\scripts\package-release.ps1
```

Outputs:
- `dist\instrument-connectivity-windows\`
- `dist\instrument-connectivity-windows-<version>.zip`

## Check Package Version

```powershell
.\bin\instrument-agent.exe -version
Get-Content .\build-metadata.json
Get-Content .\package-manifest.json
```

## Install On A Workstation
1. Extract the package zip to a stable path such as `C:\InstrumentConnectivityEngine`.
2. Open PowerShell as Administrator.
3. Install the Windows service:

```powershell
pwsh .\scripts\install-service.ps1 -BinaryPath .\bin\instrument-agent.exe -DataDir .\runtime-data
```

4. Verify the service is present in `services.msc`.
5. Open `http://127.0.0.1:9088`.

## Uninstall

```powershell
pwsh .\scripts\uninstall-service.ps1 -BinaryPath .\bin\instrument-agent.exe
```

## Upgrade Notes
- Review `docs\UPGRADE.md` before replacing an installed package.
- Compare the currently installed version with the new package version.
- Back up `runtime-data\engine.db` and `runtime-data\captures` before replacement.
- Preserve site-specific content under `runtime-data\profiles`.

## Operational Notes
- Use a stable install path; do not run the service from a temporary extraction folder.
- `runtime-data\profiles` is where site-specific profile changes should live after installation.
- `runtime-data\captures` and `runtime-data\support-bundles` should be retained for troubleshooting.
- If an API token is required, pass it during service install or reconfigure the service arguments accordingly.
- This is a script-based packaging path, not an MSI. Code signing, installer UI, and upgrade orchestration remain future work.
