#!/usr/bin/env sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
BOT="$ROOT_DIR/backend/tests/scripts/api_security_bot.py"
REPORT_DIR="$ROOT_DIR/backend/tests/reports"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="$REPORT_DIR/api_test_report_$TIMESTAMP.txt"
BASE_URL="${API_TEST_BASE_URL:-http://127.0.0.1:8000}"

mkdir -p "$REPORT_DIR"

if [ "${KEEP_REPORT_HISTORY:-0}" != "1" ]; then
  rm -f "$REPORT_DIR"/api_test_report_*.txt
fi

if ! curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
  echo "Backend preflight failed: cannot reach $BASE_URL/health"
  echo "Start backend first: cd backend && uvicorn app.main:app --reload"
  exit 2
fi

run_case() {
  title="$1"
  shift
  echo "==================================================" | tee -a "$REPORT_FILE"
  echo "$title" | tee -a "$REPORT_FILE"
  echo "Command: python $BOT $*" | tee -a "$REPORT_FILE"
  echo "--------------------------------------------------" | tee -a "$REPORT_FILE"
  python "$BOT" "$@" | tee -a "$REPORT_FILE"
  echo "" | tee -a "$REPORT_FILE"
}

echo "API security test run started at $(date)" | tee "$REPORT_FILE"
echo "Project root: $ROOT_DIR" | tee -a "$REPORT_FILE"
echo "Base URL: $BASE_URL" | tee -a "$REPORT_FILE"
echo "Keep history: ${KEEP_REPORT_HISTORY:-0}" | tee -a "$REPORT_FILE"
echo "" | tee -a "$REPORT_FILE"

run_case "FULL CHECK (ALL ENABLED ENDPOINTS)" --mode all
run_case "SMOKE CHECK" --mode all --tags smoke
run_case "PUBLIC ENDPOINTS" --mode unauth --tags public
run_case "READ ENDPOINTS" --mode all --tags read
run_case "WRITE ENDPOINTS" --mode all --tags write
run_case "AUDIO ENDPOINTS" --mode all --tags audio
run_case "SCANNER ENDPOINTS" --mode all --tags scanner
run_case "NUDGES ENDPOINTS" --mode all --tags nudges
run_case "PRESCRIPTIONS ENDPOINTS" --mode all --tags prescriptions
run_case "LINKING ENDPOINTS" --mode all --tags linking
run_case "STATUS ENDPOINTS" --mode all --tags status

echo "API security test run finished at $(date)" | tee -a "$REPORT_FILE"
echo "Report: $REPORT_FILE" | tee -a "$REPORT_FILE"
