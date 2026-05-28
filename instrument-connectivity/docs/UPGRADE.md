# Upgrade Notes

## Purpose
This file travels with packaged Windows releases so deployments have a stable place to record upgrade expectations and migration notes.

## Current Package Behavior
- Package manifests include `version`, `commit`, and `build_time` metadata.
- The release zip name includes the package version.
- `build-metadata.json` is bundled with the release.
- The binary reports its version with:

```powershell
.\bin\instrument-agent.exe -version
```

## Upgrade Checklist
1. Confirm the currently installed package version.
2. Back up `runtime-data\engine.db` and `runtime-data\captures` before replacing binaries.
3. Preserve any site-specific profiles under `runtime-data\profiles`.
4. Replace the package contents with the new release.
5. Restart the Windows service.
6. Verify `http://127.0.0.1:9088` and inspect runtime status/history.

## Migration Notes
- Current package format does not require a schema migration step beyond normal runtime startup.
- Future releases can record explicit migration requirements here and in `package-manifest.json`.
