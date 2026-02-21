# Frontend Handoff Gate

Use this checklist for frontend-only operation. Backend static pages are already removed.

## 1) API contract freeze
- Export and commit current OpenAPI:
  - `cd backend && python tests/scripts/export_openapi_contract.py`
- Treat `backend/tests/catalog/openapi_snapshot.json` as the contract snapshot for frontend integration.
- If endpoint request/response changes, regenerate snapshot in the same PR.

## 2) Security baseline
- `AUTH_REQUIRED=true`
- `AUTH_DEBUG=false`
- `ALLOWED_ORIGINS` must only contain trusted frontend domains (no `*`).

## 3) Test gate
- `sh backend/tests/scripts/final_readiness_check.sh`
- `python backend/tests/scripts/api_security_bot.py --mode unauth --tags smoke`
- With test auth configured:
  - `python backend/tests/scripts/api_security_bot.py --mode auth --tags smoke`
  - `python backend/tests/scripts/api_security_bot.py --mode all`

## 4) Frontend critical routes to verify
- `GET /health`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/bootstrap`
- `GET /api/v1/prescriptions/`
- `GET /api/v1/prescriptions/{doc_id}`
- `POST /api/v1/prescriptions/process-audio`
- `POST /api/v1/prescriptions/process-text`
- `POST /api/v1/prescriptions/finalize`
- `POST /api/v1/scanner/image`
- `GET /api/v1/nudges/*` and `GET /api/v1/status/*` routes used by UI
- `POST /api/v1/linking/*` routes used by linking UI

## 5) Static-file retirement status
- Backend static pages were removed from runtime and filesystem.
- Frontend must not reference:
  - `/static/record.html`
  - `/static/auth-test.html`
- Use API tests as replacement for old backend static test pages.

## 6) Deployment
- Run `backend-gate` GitHub Action on PRs.
- Verify production env includes Firebase credentials and required secrets.
- Confirm CORS list matches production and staging frontend URLs exactly.

## Inputs needed from you
- Final production frontend domain(s) for `ALLOWED_ORIGINS`.
- Staging domain(s) for `ALLOWED_ORIGINS`.
- Firebase test account (`TEST_EMAIL`/`TEST_PASSWORD`) and `FIREBASE_WEB_API_KEY` for auth suite automation.
