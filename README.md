# SPDXLIMS

SPDXLIMS is a Windows-first PySide6 desktop app for small clinical labs. The initial MVP focuses on manually entering patient and test data, then generating branded laboratory reports.

## Current scope
- Desktop UI with PySide6
- Local SQLite database
- Patient registration
- Lab settings with header and footer image selection
- Navigation shell for core operations, data management, settings, and Store-managed addons
- Separate Go-based instrument connectivity engine scaffold under `instrument-connectivity/`

## Run Desktop App
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Instrument Connectivity Engine
See `instrument-connectivity/README.md`.

## Downloadable Addons
SPDXLIMS is being prepared for optional desktop addons that are sold and delivered through the Microsoft Store.

- Open the `Add-ons` page in the administrative workspace.
- The base app checks whether each Store addon's optional package is installed on the device.
- Admin tools and equipment management only appear in navigation when their matching addon package is available.
- The `Add-ons` page can open the Microsoft Store product listing for each addon.

Current addon catalog targets:
- `Admin Suite`
- `Equipment Manager`
- `PDF Table Extractor`

The PDF Table Extractor addon is now intended to run inside SPDXLIMS as an integrated page built from a local copy of the extractor engine, rather than launching the old standalone app shell.

The Admin Suite addon is intended to own the full administrative area, including prices, receipt-printing workflows, billing, invoicing, inventory, and related tools. The navigation can show a placeholder page until the addon is installed.

Before shipping, replace the placeholder Microsoft Store product IDs and package family names in `spdxlims/addons.py` with the real values from Partner Center and your MSIX optional package manifests.
