from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import logging
from threading import Lock
import time
from typing import Any, Callable, Dict

from fastapi import Depends, HTTPException, Request, status
from firebase_admin import auth as firebase_auth

from app.config import settings
from app.database.firebase import db
from app.services.family_linking import get_caretaker_for_user

logger = logging.getLogger(__name__)


@dataclass
class AuthUser:
    user_id: str
    role: str
    claims: Dict[str, Any]


def _normalize_role(role: str | None) -> str:
    value = (role or "").strip().lower()
    if value in {"admin", "caretaker", "user"}:
        return value
    return "user"


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return token


def _resolve_role(uid: str, claims: Dict[str, Any]) -> str:
    role = claims.get("role")
    if role:
        return _normalize_role(str(role))

    user_doc = db.collection("users").document(uid).get()
    if user_doc.exists:
        data = user_doc.to_dict() or {}
        return _normalize_role(str(data.get("role")))
    return "user"


def get_current_user(request: Request) -> AuthUser:
    if not settings.AUTH_REQUIRED:
        return AuthUser(user_id="dev-user", role="admin", claims={})

    token = _extract_bearer_token(request)
    try:
        decoded = firebase_auth.verify_id_token(
            token,
            check_revoked=settings.FIREBASE_CHECK_REVOKED,
        )
    except Exception as e:
        error_text = str(e)
        logger.warning("Firebase token verification failed: %s", error_text)
        detail = "Invalid or expired token"
        if settings.AUTH_DEBUG:
            detail = f"Invalid or expired token: {error_text}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )

    uid = str(decoded.get("uid") or decoded.get("sub") or "")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    role = _resolve_role(uid=uid, claims=decoded)
    return AuthUser(user_id=uid, role=role, claims=decoded)


def require_roles(*roles: str) -> Callable[[AuthUser], AuthUser]:
    allowed = {_normalize_role(role) for role in roles}

    def dependency(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if current_user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return current_user

    return dependency


def require_admin(current_user: AuthUser = Depends(require_roles("admin"))) -> AuthUser:
    return current_user


def can_access_user(current_user: AuthUser, user_id: str) -> bool:
    if current_user.role == "admin":
        return True
    if current_user.user_id == user_id:
        return True
    if current_user.role == "caretaker":
        linked_caretaker = get_caretaker_for_user(user_id)
        return linked_caretaker == current_user.user_id
    return False


def ensure_user_access(current_user: AuthUser, user_id: str) -> None:
    if not can_access_user(current_user, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def can_access_caretaker(current_user: AuthUser, caretaker_id: str) -> bool:
    if current_user.role == "admin":
        return True
    if current_user.role == "caretaker":
        return current_user.user_id == caretaker_id
    if current_user.role == "user":
        linked_caretaker = get_caretaker_for_user(current_user.user_id)
        return linked_caretaker == caretaker_id
    return False


def ensure_caretaker_access(current_user: AuthUser, caretaker_id: str) -> None:
    if not can_access_caretaker(current_user, caretaker_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def can_access_prescription(current_user: AuthUser, data: Dict[str, Any]) -> bool:
    if current_user.role == "admin":
        return True
    owner_user_id = str(data.get("user_id") or "").strip()
    owner_caretaker_id = str(data.get("caretaker_id") or "").strip()
    if owner_user_id and can_access_user(current_user, owner_user_id):
        return True
    if owner_caretaker_id and can_access_caretaker(current_user, owner_caretaker_id):
        return True
    return False


def can_access_nudge(current_user: AuthUser, data: Dict[str, Any]) -> bool:
    if current_user.role == "admin":
        return True
    user_id = str(data.get("user_id") or "").strip()
    caretaker_id = str(data.get("caretaker_id") or "").strip()
    if user_id and can_access_user(current_user, user_id):
        return True
    if caretaker_id and can_access_caretaker(current_user, caretaker_id):
        return True
    return False


_RATE_STATE: Dict[str, deque[float]] = defaultdict(deque)
_RATE_LOCK = Lock()


def rate_limit(
    key_prefix: str,
    limit: int | None = None,
    window_seconds: int = 60,
) -> Callable[[Request], None]:
    max_hits = limit or settings.RATE_LIMIT_PER_MINUTE

    def dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        principal = client_ip
        if settings.AUTH_REQUIRED:
            auth_header = request.headers.get("Authorization", "")
            if auth_header:
                # Avoid storing raw token material and avoid collisions from suffix-only keys.
                principal = hashlib.sha256(auth_header.encode("utf-8")).hexdigest()
        bucket_key = f"{key_prefix}:{principal}"
        now = time.time()
        cutoff = now - window_seconds

        with _RATE_LOCK:
            hits = _RATE_STATE[bucket_key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= max_hits:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                )
            hits.append(now)

    return dependency
