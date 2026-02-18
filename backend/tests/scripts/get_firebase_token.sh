#!/usr/bin/env sh
set -eu

if [ -z "${FIREBASE_WEB_API_KEY:-}" ] || [ -z "${TEST_EMAIL:-}" ] || [ -z "${TEST_PASSWORD:-}" ]; then
  echo "Missing required env vars. Set FIREBASE_WEB_API_KEY, TEST_EMAIL, TEST_PASSWORD." 1>&2
  exit 1
fi

RESP="$(curl -s -X POST \
  "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${FIREBASE_WEB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${TEST_EMAIL}\",\"password\":\"${TEST_PASSWORD}\",\"returnSecureToken\":true}")"

ID_TOKEN="$(printf '%s' "$RESP" | python -c 'import json,sys; d=json.load(sys.stdin); print(d.get("idToken",""))')"
FIREBASE_UID="$(printf '%s' "$RESP" | python -c 'import json,sys; d=json.load(sys.stdin); print(d.get("localId",""))')"
ERR="$(printf '%s' "$RESP" | python -c 'import json,sys; d=json.load(sys.stdin); print(d.get("error",{}).get("message",""))')"

if [ -z "$ID_TOKEN" ]; then
  echo "Failed to fetch Firebase ID token. ${ERR:-Unknown error}" 1>&2
  echo "$RESP" 1>&2
  exit 1
fi

echo "export API_TEST_BEARER_TOKEN='$ID_TOKEN'"
echo "export USER_ID='${FIREBASE_UID}'"
echo "export CARETAKER_ID='${FIREBASE_UID}'"
