#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, parse, request

from dotenv import load_dotenv


PLACEHOLDER_RE = re.compile(r"\{([A-Z0-9_]+)\}")


@dataclass
class EndpointResult:
    endpoint_id: str
    mode: str
    status: str
    http_status: Optional[int]
    detail: str
    duration_ms: int


def load_local_env_files() -> None:
    # Load optional local env files so the bot works without manual export every run.
    load_dotenv(".env", override=False)
    load_dotenv("backend/.env", override=False)


def load_catalog(path: str) -> Dict[str, Any]:
    candidate = Path(path)
    if not candidate.exists():
        script_dir = Path(__file__).resolve().parent
        # Support running from any CWD with either:
        # - default "backend/tests/catalog/endpoints.json"
        # - relative "catalog/endpoints.json"
        fallback_1 = (script_dir / ".." / "catalog" / "endpoints.json").resolve()
        fallback_2 = (script_dir / path).resolve()
        if fallback_1.exists():
            candidate = fallback_1
        elif fallback_2.exists():
            candidate = fallback_2
    with open(candidate, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_placeholders(text: str, strict: bool = False) -> tuple[str, List[str]]:
    missing: List[str] = []

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        value = os.getenv(key)
        if value is None:
            missing.append(key)
            return match.group(0)
        return value

    resolved = PLACEHOLDER_RE.sub(repl, text)
    if strict and missing:
        raise ValueError(f"Missing env vars: {', '.join(sorted(set(missing)))}")
    return resolved, sorted(set(missing))


def resolve_query(query: Dict[str, Any]) -> tuple[Dict[str, str], List[str]]:
    out: Dict[str, str] = {}
    missing: List[str] = []
    for key, value in query.items():
        raw = str(value)
        resolved, missing_here = resolve_placeholders(raw)
        if missing_here:
            missing.extend(missing_here)
        out[key] = resolved
    return out, sorted(set(missing))


def build_url(base_url: str, endpoint: Dict[str, Any]) -> tuple[str, List[str]]:
    path, missing_path = resolve_placeholders(endpoint["path"])
    query = endpoint.get("query", {})
    query_resolved, missing_query = resolve_query(query) if isinstance(query, dict) else ({}, [])
    missing = sorted(set(missing_path + missing_query))
    url = base_url.rstrip("/") + path
    if query_resolved:
        url += "?" + parse.urlencode(query_resolved)
    return url, missing


def do_request(
    method: str,
    url: str,
    timeout_seconds: float,
    bearer_token: Optional[str] = None,
) -> tuple[Optional[int], str]:
    headers = {"Accept": "application/json"}
    body: Optional[bytes] = None
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    req = request.Request(url=url, method=method.upper(), headers=headers, data=body)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            return int(resp.status), ""
    except error.HTTPError as e:
        return int(e.code), str(e)
    except Exception as e:  # pragma: no cover
        return None, str(e)


def preflight_base_url(base_url: str, timeout_seconds: float) -> tuple[bool, str]:
    status, err = do_request("GET", base_url.rstrip("/") + "/health", timeout_seconds)
    if status == 200:
        return True, "Backend reachable"
    if status is None:
        return False, f"Backend unreachable: {err}"
    return False, f"Unexpected /health status: {status}"


def fetch_firebase_id_token_from_password_signin() -> tuple[Optional[str], Optional[str], str]:
    api_key = os.getenv("FIREBASE_WEB_API_KEY", "").strip()
    email = os.getenv("TEST_EMAIL", "").strip()
    password = os.getenv("TEST_PASSWORD", "")

    if not api_key or not email or not password:
        return None, None, "Set FIREBASE_WEB_API_KEY, TEST_EMAIL, and TEST_PASSWORD for auto token fetch"

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = json.dumps(
        {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        }
    ).encode("utf-8")
    req = request.Request(
        url=url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=payload,
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            token = data.get("idToken")
            uid = data.get("localId")
            if not token:
                return None, None, "Firebase sign-in response missing idToken"
            return token, uid, ""
    except error.HTTPError as e:
        try:
            details = e.read().decode("utf-8")
        except Exception:
            details = str(e)
        return None, None, f"Firebase sign-in failed: {details}"
    except Exception as e:  # pragma: no cover
        return None, None, f"Firebase sign-in failed: {e}"


def status_expected(
    endpoint: Dict[str, Any],
    mode: str,
    http_status: Optional[int],
) -> tuple[bool, str]:
    if http_status is None:
        return False, "No HTTP response"

    if mode == "unauth":
        expected = endpoint.get("expected_unauth_statuses")
        if expected is None:
            if endpoint.get("protected", True):
                expected = [401]
            else:
                expected = [200]
        if http_status in expected:
            return True, f"Expected unauth status {http_status}"
        return False, f"Expected {expected}, got {http_status}"

    expected_auth = endpoint.get("expected_auth_statuses")
    if expected_auth:
        if http_status in expected_auth:
            return True, f"Expected auth status {http_status}"
        return False, f"Expected {expected_auth}, got {http_status}"

    if http_status in (401, 403):
        return False, f"Unexpected auth failure {http_status}"
    return True, f"Auth-mode status {http_status}"


def should_include(endpoint: Dict[str, Any], tags: set[str], ids: set[str]) -> bool:
    if not endpoint.get("enabled", True):
        return False
    if ids and endpoint.get("id") not in ids:
        return False
    if tags:
        etags = set(endpoint.get("tags", []))
        if not (etags & tags):
            return False
    return True


def run_checks(
    base_url: str,
    catalog: Dict[str, Any],
    mode: str,
    tags: set[str],
    ids: set[str],
    timeout_seconds: float,
    fail_fast: bool,
) -> List[EndpointResult]:
    results: List[EndpointResult] = []
    ok, preflight_detail = preflight_base_url(base_url=base_url, timeout_seconds=timeout_seconds)
    if not ok:
        results.append(
            EndpointResult(
                endpoint_id="__preflight__",
                mode=mode,
                status="FAIL",
                http_status=None,
                detail=preflight_detail,
                duration_ms=0,
            )
        )
        return results

    token = os.getenv("API_TEST_BEARER_TOKEN")
    token_source = "env"
    if not token and mode in {"auth", "all"}:
        fetched_token, fetched_uid, token_error = fetch_firebase_id_token_from_password_signin()
        if fetched_token:
            token = fetched_token
            token_source = "firebase_password_signin"
            if fetched_uid:
                # Helpful for endpoint placeholders when UID vars are not set.
                os.environ.setdefault("USER_ID", fetched_uid)
                os.environ.setdefault("CARETAKER_ID", fetched_uid)
        else:
            token_source = f"missing ({token_error})"
    elif token and mode in {"auth", "all"}:
        # Validate provided token early; if invalid try auto-refresh from Firebase credentials.
        precheck_status, _ = do_request(
            method="GET",
            url=base_url.rstrip("/") + "/api/v1/nudges/health",
            timeout_seconds=timeout_seconds,
            bearer_token=token,
        )
        if precheck_status in (401, 403):
            fetched_token, fetched_uid, token_error = fetch_firebase_id_token_from_password_signin()
            if fetched_token:
                token = fetched_token
                token_source = "firebase_password_signin(refresh_after_env_invalid)"
                if fetched_uid:
                    os.environ.setdefault("USER_ID", fetched_uid)
                    os.environ.setdefault("CARETAKER_ID", fetched_uid)
            else:
                token = None
                token_source = f"invalid_env_token ({token_error})"

    modes = [mode] if mode in {"unauth", "auth"} else ["unauth", "auth"]

    for endpoint in catalog.get("endpoints", []):
        if not should_include(endpoint, tags=tags, ids=ids):
            continue

        url, missing_env = build_url(base_url, endpoint)
        if missing_env:
            for m in modes:
                results.append(
                    EndpointResult(
                        endpoint_id=endpoint["id"],
                        mode=m,
                        status="SKIP",
                        http_status=None,
                        detail=f"Missing env vars: {', '.join(missing_env)}",
                        duration_ms=0,
                    )
                )
            continue

        for m in modes:
            if m == "auth" and not token:
                results.append(
                    EndpointResult(
                        endpoint_id=endpoint["id"],
                        mode=m,
                        status="SKIP",
                        http_status=None,
                        detail=f"Auth token unavailable: {token_source}",
                        duration_ms=0,
                    )
                )
                continue

            start = time.time()
            http_status, error_text = do_request(
                method=endpoint["method"],
                url=url,
                timeout_seconds=timeout_seconds,
                bearer_token=token if m == "auth" else None,
            )
            duration_ms = int((time.time() - start) * 1000)
            ok, detail = status_expected(endpoint, mode=m, http_status=http_status)
            if error_text and not ok:
                detail = f"{detail}; {error_text}"

            result = EndpointResult(
                endpoint_id=endpoint["id"],
                mode=m,
                status="PASS" if ok else "FAIL",
                http_status=http_status,
                detail=detail,
                duration_ms=duration_ms,
            )
            results.append(result)

            if fail_fast and result.status == "FAIL":
                return results
    return results


def print_report(results: List[EndpointResult]) -> int:
    if not results:
        print("No endpoints matched the filter.")
        return 2

    for r in results:
        code = "-" if r.http_status is None else str(r.http_status)
        print(
            f"[{r.status}] endpoint={r.endpoint_id} mode={r.mode} status={code} "
            f"time_ms={r.duration_ms} detail={r.detail}"
        )

    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    passed = sum(1 for r in results if r.status == "PASS")
    print(
        f"\nSummary: total={len(results)} pass={passed} fail={failed} skip={skipped}"
    )
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated API security and smoke checker."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_TEST_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL for backend API",
    )
    parser.add_argument(
        "--catalog",
        default="backend/tests/catalog/endpoints.json",
        help="Path to endpoint catalog JSON",
    )
    parser.add_argument(
        "--mode",
        choices=["unauth", "auth", "all"],
        default="all",
        help="Run unauth checks, auth checks, or both",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags filter",
    )
    parser.add_argument(
        "--ids",
        default="",
        help="Comma-separated endpoint IDs filter",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at first failed check",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = load_catalog(args.catalog)
    tags = {x.strip() for x in args.tags.split(",") if x.strip()}
    ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    results = run_checks(
        base_url=args.base_url,
        catalog=catalog,
        mode=args.mode,
        tags=tags,
        ids=ids,
        timeout_seconds=args.timeout,
        fail_fast=args.fail_fast,
    )
    return print_report(results)


if __name__ == "__main__":
    sys.exit(main())
