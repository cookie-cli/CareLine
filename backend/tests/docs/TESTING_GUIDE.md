# Backend Testing Guide (Start to End)

## 1. What was added
- Automated caller security bot: `backend/tests/scripts/api_security_bot.py`
- Central endpoint registry layer: `backend/tests/catalog/endpoints.json`

You can now test endpoints by:
- all endpoints
- specific tags (`smoke`, `nudges`, `prescriptions`, etc.)
- specific endpoint IDs

## 2. Prerequisites
- Python environment with backend dependencies installed.
- Backend running locally.
- Optional auth token for authenticated test mode.

## 3. Start backend
From repo root:

```bash
cd backend
uvicorn app.main:app --reload
```

Default base URL used by bot: `http://127.0.0.1:8000`

## Browser Auth Tester (No frontend app needed)
Open:

`http://127.0.0.1:8000/static/auth-test.html`

Flow:
1. Paste Firebase web config JSON.
2. Initialize Firebase.
3. Sign in with test email/password.
4. Run unauth/auth endpoint calls and smoke series.

## 4. Configure test environment variables
In another terminal:

```bash
export API_TEST_BASE_URL="http://127.0.0.1:8000"
export API_TEST_BEARER_TOKEN="<firebase_id_token>"
export CARETAKER_ID="<caretaker_uid>"
export USER_ID="<user_uid>"
export PRESCRIPTION_ID="<existing_prescription_id>"
export LINK_CODE="<link_code_if_needed>"
```

Notes:
- `API_TEST_BEARER_TOKEN` is required for `--mode auth` and `--mode all` auth checks.
- Endpoints with placeholders are skipped if matching env vars are not set.

### Auto-fetch bearer token (no manual token copy)
If `API_TEST_BEARER_TOKEN` is not set, the bot can fetch a fresh Firebase ID token automatically when these are set:

```bash
export FIREBASE_WEB_API_KEY="your_web_api_key"
export TEST_EMAIL="your_test_email"
export TEST_PASSWORD="your_test_password"
```

The bot will sign in via Firebase REST API and use that `idToken` for auth-mode checks.

### Reliable shell token export helper
Instead of manual token extraction, run:

```bash
eval "$(sh backend/tests/scripts/get_firebase_token.sh)"
```

This sets:
- `API_TEST_BEARER_TOKEN`
- `USER_ID`
- `CARETAKER_ID`

## 5. Run the bot
From repo root:

### A) Security check: unauthenticated access should fail on protected endpoints
```bash
python backend/tests/scripts/api_security_bot.py --mode unauth
```

### B) Authenticated smoke check
```bash
python backend/tests/scripts/api_security_bot.py --mode auth
```

### C) Full run (unauth + auth)
```bash
python backend/tests/scripts/api_security_bot.py --mode all
```

### D) Only smoke endpoints
```bash
python backend/tests/scripts/api_security_bot.py --mode all --tags smoke
```

### E) Specific endpoint IDs
```bash
python backend/tests/scripts/api_security_bot.py --ids prescriptions_list,nudges_health --mode all
```

### F) Full suite with one command (report generated)
```bash
sh backend/tests/scripts/run_all_tests.sh
```

Generated report path:
- `backend/tests/reports/api_test_report_<timestamp>.txt`

Default rerun behavior:
- old report files are auto-removed before a new run.
- set `KEEP_REPORT_HISTORY=1` if you want to keep previous reports.

## 6. How to customize endpoints
Edit:
- `backend/tests/catalog/endpoints.json`

Each endpoint supports:
- `id` unique key
- `method` (`GET`, `POST`, etc.)
- `path` with placeholders like `{USER_ID}`
- `query` object (optional)
- `protected` boolean
- `expected_unauth_statuses` list
- `expected_auth_statuses` list
- `tags` list
- `enabled` boolean

## 7. Interpreting output
- `PASS`: endpoint behavior matched expected status rules.
- `FAIL`: status did not match expected behavior.
- `SKIP`: missing token/env placeholders or endpoint disabled.

Non-zero exit code means failures were found.

Token handling behavior:
- If `API_TEST_BEARER_TOKEN` is invalid, bot tries auto-refresh using Firebase credentials.
- If refresh fails, auth-mode checks are skipped with one clear reason instead of noisy repeated failures.

## Final readiness gate (before frontend/release)
Run:

```bash
sh backend/tests/scripts/final_readiness_check.sh
```

This checks:
- compile sanity
- secret-file tracking in git
- secure runtime flags (`AUTH_DEBUG`, `ENABLE_TEST_TOOLS`, `AUTH_REQUIRED`)
- optional runtime `/health` preflight

## 8. Suggested full validation order
1. `--mode unauth --tags smoke` (fast policy sanity)
2. `--mode unauth` (full protection check)
3. `--mode auth --tags smoke` (core availability)
4. `--mode auth` (full authenticated suite)
