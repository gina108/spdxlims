# Instrument Connectivity Addon Integration Contract

## Positioning

`instrument-connectivity` should be sold as a local companion service for the LIMS, not as a library embedded directly into the main application.

Recommended deployment model:

- Windows service or background process on the same workstation/server as the LIMS
- `localhost` HTTP API for the LIMS UI and backend
- local persistence for captures, replay, diagnostics, and support bundles
- explicit operator review before final result posting when required by workflow

This keeps analyzer-specific behavior isolated from the core LIMS and makes device support easier to version, validate, and troubleshoot.

## System Boundary

The addon is responsible for:

- instrument connectivity
- raw payload capture
- protocol classification
- parsing into canonical observation data
- profile-driven mapping and normalization
- replay and diagnostics

The LIMS is responsible for:

- patient/order context
- final accession/result ownership
- user authentication and authorization
- review/approval workflow
- final posting into the clinical record
- audit policy and retention policy at the business level

## Recommended Integration Pattern

Recommended pattern for commercial use:

1. The addon runs locally and listens on `127.0.0.1`.
2. The LIMS admin UI configures profiles, ports, and connectivity through the addon API.
3. The addon parses inbound analyzer data into a canonical result payload.
4. The LIMS pulls or receives parsed results and matches them to orders/specimens.
5. The LIMS presents exceptions for human review when mapping or identification is uncertain.
6. The LIMS commits approved results into the patient record.

## Current HTTP Surface

The current server in [server.go](C:\SPDXLIMS\instrument-connectivity\internal\api\server.go) exposes:

- `GET /health`
- `GET /api/ports/scan`
- `POST /api/capture/start`
- `POST /api/capture/stop`
- `GET /api/captures`
- `POST /api/classify`
- `POST /api/parse`
- `GET|POST|PUT /api/profiles`
- `POST /api/map`
- `POST /api/replay`
- `POST /api/learning/suggest`
- `GET /api/support-bundle`

For productization, the LIMS should treat `POST /api/parse` as the main ingestion endpoint and the others as admin/support endpoints.

## Commercial API Split

Recommended split:

### Runtime endpoints

- `GET /health`
- `POST /api/parse`
- `POST /api/replay`

### Admin endpoints

- `GET /api/ports/scan`
- `GET|POST|PUT /api/profiles`
- `POST /api/capture/start`
- `POST /api/capture/stop`
- `GET /api/captures`
- `POST /api/learning/suggest`
- `GET /api/support-bundle`

This prevents the LIMS runtime integration from depending on discovery and debugging endpoints.

## Canonical Result Payload

The addon should return a stable canonical payload shaped around the internal models in [models.go](C:\SPDXLIMS\instrument-connectivity\internal\models\models.go):

- message metadata
- source device/profile identifiers
- protocol and transport type
- received timestamp
- parsed observations
- mapping trace
- raw payload reference
- classification details

Recommended commercial contract for parsed results:

```json
{
  "capture": {
    "id": "cap_123",
    "profile_id": "generic-hl7",
    "device_id": "analyzer-1"
  },
  "result": {
    "message": {
      "message_id": "msg_123",
      "source_device_id": "analyzer-1",
      "source_profile_id": "generic-hl7",
      "protocol_type": "hl7_v2",
      "transport_type": "tcp_client",
      "received_at": "2026-03-21T18:00:00Z",
      "sample_id": "SAMPLE1",
      "patient_id": "PAT123",
      "accession_id": "ACC42",
      "observations": [
        {
          "observation_id": "obx_1",
          "instrument_test_code": "GLU",
          "instrument_test_name": "Glucose",
          "mapped_lis_test_id": "GLUCOSE",
          "value_raw": "108",
          "value_numeric": 108,
          "units_raw": "mg/dL",
          "units_normalized": "mg/dL",
          "abnormal_flag": "N",
          "reference_range": "70-110",
          "result_status": "F"
        }
      ]
    },
    "classification": {
      "selected": "hl7_v2"
    },
    "mapping_trace": [
      "matched GLU to GLUCOSE"
    ]
  }
}
```

## LIMS Responsibilities After Parse

The LIMS should add the business/clinical decisions that do not belong in the addon:

- match `sample_id`, `patient_id`, or `accession_id` to an open order
- reject unmatched or ambiguous results
- require review when the mapping trace shows uncertainty
- prevent duplicate posting
- record operator identity for approval
- control whether corrected/amended results are allowed

## Required Hardening Before Sale

The current code is a solid prototype, but not yet a sellable addon. Minimum gaps to close:

- authentication or shared-secret protection for API calls
- versioned API namespace such as `/api/v1/...`
- structured logging with correlation ids
- explicit error codes instead of free-text only
- Windows service installation and service recovery behavior
- configuration backup/export/import
- retention settings for captures and support data
- health/readiness details beyond a simple `ok`
- installer and upgrade path
- licensing/activation

## Clinical Workflow Guardrails

For a laboratory product, avoid implying that the addon independently validates clinical correctness. The addon should be positioned as:

- a connectivity and normalization layer
- deterministic and auditable
- review-friendly
- replayable for support and validation

The LIMS should remain the system of record for final accepted results.

## Recommended Next Implementation Steps

1. Add `/api/v1` routes and freeze the request/response schema.
2. Add API authentication for local LIMS-to-addon calls.
3. Add a `POST /api/v1/results/ingest` or reuse `POST /api/v1/parse` as the single runtime endpoint.
4. Add machine-readable error codes and validation responses.
5. Add Windows service packaging and installer support.
6. Add an outbound handoff mode if the LIMS prefers polling or callback delivery.

## Suggested Product Message

Good message:

- "Local analyzer connectivity addon for your LIMS with capture, replay, profile-based parsing, and audit-friendly troubleshooting."

Avoid message:

- "Automatically understands any analyzer protocol."

The first is defensible. The second creates support and compliance risk immediately.
