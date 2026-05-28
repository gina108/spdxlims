# NIIMBOT Helper

Small local HTTP helper for direct NIIMBOT printing from SPDXLIMS.

## V1 API

### `GET /health`

Response:

```json
{
  "ok": true,
  "version": "0.1.0"
}
```

### `GET /printers`

Response:

```json
[
  {
    "id": "usb:niimbot_b1",
    "model": "NIIMBOT B1",
    "connection": "usb",
    "status": "ready"
  }
]
```

### `POST /print/niimbot-label`

Request:

```json
{
  "printer_id": "usb:niimbot_b1",
  "label": {
    "width_mm": 50,
    "height_mm": 30
  },
  "content": {
    "barcode_type": "code39",
    "barcode_value": "000014",
    "human_text": "000014",
    "text_lines": ["Temperence Brennan Booth"]
  },
  "copies": 1
}
```

Response:

```json
{
  "ok": true,
  "job_id": "job_123abc456def"
}
```

## Run

```powershell
go run .\cmd\helper
```

## Current status

This scaffold is intentionally stubbed:

- `GET /health` works
- `GET /printers` returns a placeholder NIIMBOT B1 USB printer
- `POST /print/niimbot-label` validates the request and returns a job id

Next step:

- replace the stub printer service with real USB NIIMBOT B1 discovery and print transport
