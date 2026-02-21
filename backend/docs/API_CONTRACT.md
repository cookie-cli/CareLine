# API Contract Notes

## Base
- Base URL: `http://127.0.0.1:8000`
- API prefix: `/api/v1`
- Health: `GET /health`
- Realtime WebSocket: `GET ws://127.0.0.1:8000/api/v1/nudges/ws?token=<firebase_id_token>`

## Realtime nudges
- Connect to `/api/v1/nudges/ws` with Firebase ID token as query param (`token`) or `Authorization: Bearer <token>`.
- Server sends:
  - `{"type":"connected","rooms":[...],"user_id":"...","role":"..."}`
  - `{"type":"nudge_event","event":"created|updated","nudge":{...}}`
- Ping support:
  - client sends `ping`
  - server replies `{"type":"pong"}`

## Error response shape (standardized)
All API errors now return:

```json
{
  "success": false,
  "error": {
    "code": "validation_error | http_<status> | internal_error",
    "message": "human readable message",
    "request_id": "uuid or propagated X-Request-ID",
    "details": {}
  }
}
```

`details` is present for validation errors and structured error payloads.

## Contract snapshot
- Generate OpenAPI snapshot:
  - `cd backend && python tests/scripts/export_openapi_contract.py`
- Snapshot file:
  - `backend/tests/catalog/openapi_snapshot.json`

Commit snapshot changes with any endpoint request/response change so frontend can track API drift.
