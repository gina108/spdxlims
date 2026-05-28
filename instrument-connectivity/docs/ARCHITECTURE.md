# Instrument Connectivity Engine Architecture

## Overview
The engine is a separate local Go runtime intended to run beside the LIS. It prioritizes deterministic behavior, local persistence, replayability, support diagnostics, and Windows-first deployability over opaque automation.

## Transport Layer
- Discovery enumerates serial ports, captures USB metadata when available, and performs bounded TCP endpoint discovery across local private subnets, configured CIDRs, and operator-supplied scan targets.
- Session handling is designed around pluggable transports: serial, TCP client, TCP server, and file-drop.
- Candidate serial parameter scoring is implemented for common defaults such as `9600 8N1`, `19200 8N1`, `38400 8N1`, and `9600 7E1`.
- Long-lived file-drop, TCP client, TCP server, and serial workers are implemented with reconnect and state tracking.
- ASTM-aware framing, ACK/NAK handling, and checksum validation are implemented as a practical first inbound-focused layer, not a complete analyzer-specific conversational state machine.
- Network discovery is intentionally conservative: it tests configured ports, records reachability and latency, performs a short passive banner read on endpoints that immediately speak after connect, and only sends a minimal HTTP `HEAD` probe to common HTTP-style admin ports.
- Common LIS port ranges are exposed as protocol hints rather than aggressive active fingerprinting, and only a small CRLF greeting probe is used for classic line-oriented admin ports where that behavior is expected.

## Classifier
The classifier is rule-based and returns scored candidates, not a single hard decision. Signals include HL7 markers, ASTM markers, printable ratio, delimiter frequency, STX/ETX, ASTM session control characters, and line-vs-binary structure.

## Parser Pipeline
1. Preserve raw bytes.
2. Decode text with ASCII, UTF-8, then Latin-1/Windows-1252 fallback.
3. Normalize line endings and control noise.
4. Classify protocol.
5. Parse into canonical `InstrumentMessage` and `Observation` structures.
6. Apply profile-driven mapping rules and unit normalization.
7. Persist capture, decoded text, classification, normalized output, and diagnostics for replay and support.

## Canonical Schema
The internal schema centers on `InstrumentMessage` for source metadata and `Observation` for analyzer test code, values, units, flags, ranges, status, and LIS mapping output.

## Mapping Model
Profiles define transport configuration, parsing strategy hints, field extraction intent, test code aliases, exact/contains/regex mappings, unit normalization, and QC ignore rules.

Unmapped observations are persisted separately so support or implementation staff can review unknown analytes and extend profiles without losing source context.

## Learning Mode
Learning mode is intentionally rule-based. Captured traffic is stored, repeated delimiters and candidate column positions are suggested, and the user can confirm mappings to create a reusable profile.

## Observability
This iteration includes:
- raw capture retention
- decoded and normalized views
- classifier scores
- replay
- mapping trace
- runtime status by profile/device
- persisted network-device inventory with seen counts, first-seen/last-seen timestamps, banner snapshots, subnet/interface sighting history, and history-backed stability scoring
- explicit endpoint-to-runtime correlation so discovered network devices can accumulate capture counts, replay status, and recent parse failures even when analyzer runtime IDs change
- manual runtime-link overrides are persisted separately so support staff can correct endpoint correlation without editing capture records
- runtime links carry both `source` and `confidence` so automatic correlations can be distinguished from manual confirmations during support review
- live session state and session history
- last successful communication time
- recent runtime error log
- unmapped observation queue
- maintenance status for retention cleanup
- support bundle export, including `network-links.json` and `network-link-summary.json` for runtime-link source/confidence diagnostics
- runtime-link audit log for manual confirms, overrides, deletes, imports, and migration-bundle actions

## Local API
The engine exposes versioned local endpoints under `/api/v1`. The main runtime ingest alias is `POST /api/v1/results/ingest`.

Network-device operations lean on:
- `GET /api/v1/ports/scan` for ad hoc serial and network discovery with optional CIDR/port overrides
- `GET /api/v1/runtime/status` for the persisted runtime snapshot, including discovered network devices and their history
- `GET /api/v1/captures?device_id=...` or `GET /api/v1/captures?device_ids=...` for recent captures tied to a selected endpoint and its correlated runtime identities
- `POST /api/v1/network-links` and `DELETE /api/v1/network-links` for manual endpoint-to-runtime link confirmation or override from the local UI
- `GET /api/v1/network-links/export`, `GET /api/v1/network-links/audit`, `GET /api/v1/network-links/audit/export`, `POST /api/v1/network-links/preview-import`, and `POST /api/v1/network-links/import` for moving confirmed endpoint links between installs, previewing conflicts, reviewing audit history, exporting audit evidence, and applying manual merge decisions
- `GET /api/v1/migration-bundle/export`, `POST /api/v1/migration-bundle/preview`, and `POST /api/v1/migration-bundle/import` for full profile-plus-link site migration bundles with integrity validation and profile diff preview

## Profile Discovery Hints
Profiles can opt into additional discovery behavior with `transport.discovery_hints`. The first implementation keeps this intentionally narrow:
- `hl7_listener` adds common HL7/MLLP listener ports
- `http_admin` adds common HTTP admin ports
- `raw_socket` adds raw-socket listener ports such as `9100`
- `line_admin` adds classic line-oriented admin ports used by narrow CRLF greeting probes

The local admin UI now exposes `discovery_hints` editing directly through the profile panel so support staff can manage these hints without editing YAML by hand.
The profile editor also presents preset hint buttons, validation, and per-hint port expansion help so unsupported values are caught before they reach disk and operators can see the concrete scan impact of each hint.

Runtime-link import is intentionally conflict-aware. If an imported payload tries to claim a runtime device for a different endpoint, or tries to replace a different runtime on the same endpoint/profile pair, the UI surfaces that as a manual merge choice instead of silently overwriting site state.
Manual link actions and import/merge operations are written to a local audit log with operator name, action type, timestamps, and summary detail so support work is reviewable after the fact.
Migration bundles now carry both a payload SHA-256 checksum and an HMAC-SHA256 signature. Preview/import validates both before reporting profile diffs or writing site state. The default runtime can persist a local signing secret under the data directory, while deployments that need cross-site verification should set a shared `INSTRUMENT_BUNDLE_HMAC_SECRET`. The admin UI surfaces whether the current site is using a shared configured secret or a locally generated one.
Profile diff preview is field-level rather than section-only, so support staff can see exact changed paths like `transport.remote_address` or `mapping.test_mappings`, along with old/new values for faster review.
The local UI also renders side-by-side diff cards for changed profile fields so operators can compare current and incoming values without reading raw JSON alone.
Audit exports and migration bundle exports also support optional redaction presets. The current presets are `transport_only`, `metadata_only`, `identifiers_only`, and `external_share`. They focus on redacting operators, runtime IDs, endpoint identifiers, transport addresses, watch paths, discovery CIDRs, and device metadata while leaving structural diagnostics intact.
Bundle export and import actions are written into the existing audit trail with actor, counts, redaction state, and merge context so site-transfer activity is traceable.

If `INSTRUMENT_API_TOKEN` or `-api-token` is configured, `/api` and `/api/v1` endpoints require a shared token while health and static UI remain accessible.

## Windows Runtime Model
- The same agent binary supports both interactive console execution and native Windows service execution.
- Service installation and removal are built into the binary via `-install-service` and `-uninstall-service`.
- PowerShell helper scripts under `scripts/` build the release binary and wrap the service install/uninstall flow.
- The architecture stays portable by keeping Windows SCM logic isolated behind platform-specific files.

## Limitations
- No reverse engineering of arbitrary binary proprietary protocols.
- Binary opaque payloads are captured and classified, but deep proprietary binary decoding remains future work.
- ASTM behavior is still a generic inbound implementation, not a full analyzer-certified session engine for every instrument family.
- Auth is a shared-secret local API guard, not a full user-management system.
- The UI is intentionally minimal and support-oriented rather than polished.
