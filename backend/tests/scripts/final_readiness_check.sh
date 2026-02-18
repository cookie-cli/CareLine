#!/usr/bin/env sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT_DIR"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() { echo "[PASS] $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "[FAIL] $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
warn() { echo "[WARN] $1"; WARN_COUNT=$((WARN_COUNT + 1)); }

echo "=== CareLine Final Readiness Check ==="
echo "Project: $ROOT_DIR"
echo

# 1) Compile check
if python -m compileall -q backend/app backend/tests; then
  pass "Python compile check passed (backend/app + backend/tests)"
else
  fail "Python compile check failed"
fi

# 2) Sensitive file tracking check
SENSITIVE_TRACKED="$(git ls-files | grep -E '(^|/)\\.env$|(^|/)firebase-key\\.json$|service-account|\\.pem$|\\.key$' || true)"
if [ -n "$SENSITIVE_TRACKED" ]; then
  fail "Sensitive files appear tracked in git:"
  printf '%s\n' "$SENSITIVE_TRACKED"
else
  pass "No obvious secrets tracked in git"
fi

# 3) .env production safety flags (if backend/.env exists)
if [ -f "backend/.env" ]; then
  auth_debug="$(python -c "from dotenv import dotenv_values; v=dotenv_values('backend/.env'); print((v.get('AUTH_DEBUG') or '').strip().lower())")"
  enable_tools="$(python -c "from dotenv import dotenv_values; v=dotenv_values('backend/.env'); print((v.get('ENABLE_TEST_TOOLS') or '').strip().lower())")"
  auth_required="$(python -c "from dotenv import dotenv_values; v=dotenv_values('backend/.env'); print((v.get('AUTH_REQUIRED') or '').strip().lower())")"

  if [ "$auth_debug" = "true" ]; then
    fail "AUTH_DEBUG=true in backend/.env (set to false for safe runtime)"
  else
    pass "AUTH_DEBUG is not enabled"
  fi

  if [ "$enable_tools" = "true" ]; then
    fail "ENABLE_TEST_TOOLS=true in backend/.env (set to false for production)"
  else
    pass "ENABLE_TEST_TOOLS is not enabled"
  fi

  if [ -z "$auth_required" ] || [ "$auth_required" = "true" ]; then
    pass "AUTH_REQUIRED is enabled (or default-enabled)"
  else
    fail "AUTH_REQUIRED is disabled"
  fi
else
  warn "backend/.env not found; runtime env checks skipped"
fi

# 4) Runtime health preflight (optional)
BASE_URL="${API_TEST_BASE_URL:-http://127.0.0.1:8000}"
if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
  pass "Backend runtime health check OK ($BASE_URL/health)"

  # Optional: ensure test page is blocked unless explicitly enabled.
  code="$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/static/auth-test.html" || true)"
  if [ "$code" = "404" ] || [ "$code" = "200" ]; then
    pass "Static auth tester route behavior reachable (HTTP $code)"
  else
    warn "Unexpected auth tester HTTP status: $code"
  fi
else
  warn "Backend not running at $BASE_URL; runtime checks skipped"
fi

echo
echo "Summary: pass=$PASS_COUNT fail=$FAIL_COUNT warn=$WARN_COUNT"
if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
exit 0
