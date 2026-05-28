# Instrument Connectivity Engine

A Windows-first local connector service for clinical instruments. The service is structured as a universal runtime with plugins/adapters, capture persistence, rule-based classification, protocol parsing, profile-driven mapping, replay, learning-mode suggestions, runtime diagnostics, and retention cleanup.

## What This Iteration Includes
- local HTTP service on `localhost`
- bounded local-network detection for likely instrument endpoints on private subnets
- operator-supplied CIDR and port overrides in the local scan UI/API
- SQLite-backed capture, session, learning, runtime status, unmapped queue, error-log, session-history, and maintenance-status persistence
- persisted network-device history with seen counts, last-seen tracking, stability scoring, and banner snapshots
- subnet and interface sighting history to explain why a network device looks stable or unstable
- explicit correlation between discovered network endpoints and analyzer runtime device IDs so capture/replay actions survive identifier changes
- manual runtime-link confirmation and override support for support staff when automatic endpoint correlation is incomplete
- runtime link confidence labeling plus export/import flows for moving confirmed correlations between sites
- YAML-based profiles with seed examples
- protocol classifier for HL7, ASTM, CSV, line text, framed text, and binary-like payloads
- serial and network discovery output from the scan API
- conservative banner probing for immediately talkative TCP endpoints
- safe protocol-aware probes for common HTTP-style admin ports, plus port-hint classification for common HL7/raw-socket listener patterns
- narrow CRLF greeting probes for classic line-oriented admin ports and replay-event tracking for endpoint health summaries
- opt-in profile `discovery_hints` for known analyzer families so extra probe ports stay scoped to configured instruments
- local UI controls for editing `discovery_hints` with preset buttons, per-hint port help, and validation, without hand-editing YAML profiles
- parsers for HL7 ORU-style messages, ASTM result records, CSV, generic line text, and raw fallback
- mapping engine with aliases, exact/contains/regex matching, unit normalization, QC filtering, unmapped observation tracking, and trace output
- replay from saved captures or a file path
- minimal admin UI under `web/`
- runtime diagnostics endpoints for device health, recent errors, session history, unmapped observations, and cleanup state
- retention enforcement on startup, scheduled cleanup, and an on-demand cleanup action
- native Windows service install/run/uninstall support
- PowerShell release, package, and service install scripts under `scripts/`
- embedded build metadata with `-version` output
- support bundle export including captures, profiles, runtime status, runtime errors, session history, raw runtime-link exports, and runtime-link source/confidence summaries
- fixtures and tests for core parsing, transport, runtime, and maintenance logic

## Install
1. Install Go 1.22 or later.
2. From `instrument-connectivity/`, run:

```powershell
go mod tidy
go run ./cmd/agent -data-dir .runtime
```

3. Open `http://127.0.0.1:9088`.

## Binary Version Info
The built binary reports its release identity:

```powershell
.\bin\instrument-agent.exe -version
```

## Windows Release Build
Build a Windows executable with version metadata:

```powershell
pwsh .\scripts\build-release.ps1
```

This creates:
- `bin\instrument-agent.exe`
- `bin\build-metadata.json`

## Windows Package Build
Build a distributable Windows package folder and versioned zip:

```powershell
pwsh .\scripts\package-release.ps1
```

Outputs:
- `dist\instrument-connectivity-windows\`
- `dist\instrument-connectivity-windows-<version>.zip`

Deployment details are documented in [WINDOWS_DEPLOYMENT.md](C:\SPDXLIMS\instrument-connectivity\docs\WINDOWS_DEPLOYMENT.md), and upgrade guidance is in [UPGRADE.md](C:\SPDXLIMS\instrument-connectivity\docs\UPGRADE.md).

## Windows Service Install
Install the built executable as a native Windows service:

```powershell
pwsh .\scripts\install-service.ps1 -BinaryPath .\bin\instrument-agent.exe -DataDir C:\ProgramData\InstrumentConnectivityEngine
```

The binary also supports direct service management:

```powershell
.\bin\instrument-agent.exe -install-service -service-name InstrumentConnectivityEngine -data-dir C:\ProgramData\InstrumentConnectivityEngine
.\bin\instrument-agent.exe -uninstall-service -service-name InstrumentConnectivityEngine
```

Default service settings:
- service name: `InstrumentConnectivityEngine`
- display name: `Instrument Connectivity Engine`
- start type: automatic

After installation, manage it with normal Windows service tools such as `services.msc` or `sc.exe`.

## Optional API Token
If you want to protect `/api` and `/api/v1` endpoints locally, set a shared token:

```powershell
$env:INSTRUMENT_API_TOKEN = "replace-with-shared-secret"
go run ./cmd/agent -data-dir .runtime
```

You can also pass `-api-token your-secret`.

When a token is configured, use either:
- `X-API-Key: your-secret`
- `Authorization: Bearer your-secret`

## Retention Flags
The agent applies retention once during startup, runs it on a background schedule, and can also run it on demand.

```powershell
go run ./cmd/agent -data-dir .runtime -retention-days 30 -session-event-max 5000 -runtime-error-max 2000 -capture-max 2000 -cleanup-interval 6h
```

Available flags:
- `-retention-days`
- `-session-event-max`
- `-runtime-error-max`
- `-capture-max`
- `-cleanup-interval` with Go duration syntax such as `30m`, `6h`, or `0` to disable scheduled cleanup

## Replay CLI
```powershell
go run ./cmd/agent -data-dir .runtime -profile generic-hl7 -replay fixtures/hl7_oru.txt
```

## Versioned API Surface
Core runtime/admin endpoints:
- `GET /api/v1/health`
- `GET /api/v1/ports/scan`
- `POST /api/v1/capture/start`
- `POST /api/v1/capture/stop`
- `GET /api/v1/captures`
- `POST|DELETE /api/v1/network-links`
- `GET /api/v1/network-links/export`
- `GET /api/v1/network-links/audit`
- `GET /api/v1/network-links/audit/export`
- `POST /api/v1/network-links/preview-import`
- `POST /api/v1/network-links/import`
- `GET /api/v1/migration-bundle/export`
- `POST /api/v1/migration-bundle/preview`
- `POST /api/v1/migration-bundle/import`
- `POST /api/v1/classify`
- `POST /api/v1/parse`
- `POST /api/v1/results/ingest`
- `GET|POST|PUT /api/v1/profiles`
- `POST /api/v1/map`
- `POST /api/v1/replay`
- `POST /api/v1/learning/suggest`
- `GET /api/v1/runtime/status`
- `GET /api/v1/runtime/errors`
- `GET /api/v1/runtime/history`
- `POST /api/v1/runtime/cleanup`
- `GET /api/v1/support-bundle`

Legacy `/api/...` routes remain for backward compatibility.

`GET /api/v1/ports/scan` accepts optional query parameters:
- `cidrs=192.168.1.0/24,10.10.20.0/24`
- `ports=5000,2575,9100`

`GET /api/v1/captures` accepts optional query parameters:
- `device_id=net:192.168.1.10`
- `profile_id=generic-hl7`
- `limit=5`

## UI Notes
The local UI now:
- uses `/api/v1`
- supports an optional API token stored in browser local storage
- lets operators provide scan CIDRs and scan ports for targeted network discovery
- includes a dedicated network devices page with text/status/protocol filters, last-seen status, subnet/interface history, and replay actions for recent captures
- includes a runtime-link inspector so support staff can confirm, replace, or remove endpoint-to-analyzer correlations
- includes profile editing controls for `discovery_hints`, preset validation, and runtime link export/import for site migrations
- shows per-hint help text with the ports each supported discovery hint expands to
- previews runtime-link import conflicts and supports manual keep-existing vs use-imported merge decisions
- records runtime-link audit events for manual confirms, overrides, deletes, imports, and migration-bundle actions with operator name and timestamp
- supports JSON migration bundle export/import for profiles plus confirmed runtime links
- previews field-level profile bundle diffs before import, including exact changed paths plus old/new values under `transport`, `parsing`, `mapping`, and related sections
- renders side-by-side visual diff cards in the local UI so support staff can review current vs incoming profile values faster
- supports downloadable filtered audit exports for support tickets and site turnover, with optional redaction for external sharing
- signs migration bundles with HMAC-SHA256 and still includes payload checksums for easier diagnostics
- shows whether bundle signing is using a shared configured HMAC secret or a locally generated site secret
- supports optional migration-bundle redaction presets such as `transport_only`, `metadata_only`, `identifiers_only`, and `external_share`
- records bundle export/import actions in the audit log so support can see who exported redacted vs full bundles and when
- shows bundle export/import events in a dedicated summarized section above the raw audit stream, including actor, time, redaction mode, counts, and merge outcomes
- supports audit filtering by operator, profile, endpoint, and action in the local UI
- shows serial ports and discovered network devices, including open ports, banner details, likely protocol hints, correlated runtime IDs, capture counts, replay history, parse-failure excerpts, and last replay status
- shows ports, profiles, captures, runtime status, runtime errors, and session history
- provides a maintenance panel for retention cleanup and report review
- provides a support-bundle diagnostics panel with runtime-link source/confidence summaries before download

## Assumptions
- first iteration is inbound-result focused
- localhost-only admin surface with optional shared-secret protection
- deterministic heuristics are preferred over ML
- poor or undocumented instruments are handled through raw capture, replay, classifier scores, learning suggestions, and unmapped queues rather than magic autodetection claims
- Windows deployment is prioritized first, with service integration implemented and portable non-Windows stubs preserved

## Development Checks
```powershell
go build ./...
go test ./...
```
