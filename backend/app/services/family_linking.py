from __future__ import annotations

from datetime import datetime, timedelta
import secrets
import string
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from firebase_admin import firestore

from app.config import link_code_hash, settings
from app.database.firebase import db


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def _generate_link_code(length: int | None = None) -> str:
    # Avoid ambiguous characters to reduce user entry mistakes.
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    size = max(6, int(length or settings.LINK_CODE_LENGTH))
    return "".join(secrets.choice(alphabet) for _ in range(size))


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _find_code_doc(normalized_code: str):
    code_hash = link_code_hash(normalized_code)
    docs = (
        db.collection("link_codes")
        .where("code_hash", "==", code_hash)
        .limit(1)
        .stream()
    )
    for doc in docs:
        return doc
    return None


def create_caretaker_link_code(caretaker_id: str, expires_minutes: int = 30) -> Dict[str, Any]:
    normalized_code = ""
    code_hash = ""
    for _ in range(5):
        candidate = _normalize_code(_generate_link_code())
        candidate_hash = link_code_hash(candidate)
        existing = (
            db.collection("link_codes")
            .where("code_hash", "==", candidate_hash)
            .where("used", "==", False)
            .limit(1)
            .stream()
        )
        if not any(True for _doc in existing):
            normalized_code = candidate
            code_hash = candidate_hash
            break
    if not normalized_code:
        raise RuntimeError("Unable to allocate unique link code")
    expires_at = (datetime.utcnow() + timedelta(minutes=expires_minutes)).isoformat()
    code_id = secrets.token_urlsafe(18)
    qr_payload = f"{settings.LINK_QR_BASE_URL}?code={normalized_code}"

    payload = {
        "code_hash": code_hash,
        "code_hint": normalized_code[-4:],
        "code_length": len(normalized_code),
        "caretaker_id": caretaker_id,
        "created_at": now_iso(),
        "expires_at": expires_at,
        "used": False,
        "used_by": None,
        "failed_attempts": 0,
        "locked": False,
        "qr_payload": qr_payload,
    }
    db.collection("link_codes").document(code_id).set(payload)
    return {
        **payload,
        "id": code_id,
        "code": normalized_code,
    }


def extract_code_from_qr_payload(qr_payload: str) -> str:
    raw = (qr_payload or "").strip()
    if not raw:
        return ""
    if "://" in raw or raw.startswith("careline:"):
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        return _normalize_code(code)
    return _normalize_code(raw)


def connect_user_with_code(user_id: str, code: str) -> Dict[str, Any]:
    normalized_code = _normalize_code(code)
    if not normalized_code:
        return {"success": False, "error": "Invalid code"}

    code_doc = _find_code_doc(normalized_code)
    if not code_doc:
        return {"success": False, "error": "Invalid code"}

    code_data = code_doc.to_dict() or {}
    if code_data.get("locked"):
        return {"success": False, "error": "Code temporarily locked due to invalid attempts"}
    if code_data.get("used"):
        return {"success": False, "error": "Code already used"}

    expires_at = code_data.get("expires_at")
    if expires_at and datetime.fromisoformat(expires_at) < datetime.utcnow():
        return {"success": False, "error": "Code expired"}

    caretaker_id = code_data.get("caretaker_id")
    if not caretaker_id:
        return {"success": False, "error": "Code data invalid"}

    if caretaker_id == user_id:
        return {"success": False, "error": "Caretaker and user cannot be the same account"}

    link_id = f"{caretaker_id}_{user_id}"
    link_payload = {
        "caretaker_id": caretaker_id,
        "user_id": user_id,
        "active": True,
        "created_at": now_iso(),
        "source": "invite_code",
        "code": normalized_code,
    }
    db.collection("care_links").document(link_id).set(link_payload, merge=True)

    db.collection("users").document(caretaker_id).set(
        {
            "role": "caretaker",
            "linked_users": firestore.ArrayUnion([user_id]),
            "updated_at": now_iso(),
        },
        merge=True,
    )
    db.collection("users").document(user_id).set(
        {
            "role": "user",
            "caretaker_id": caretaker_id,
            "updated_at": now_iso(),
        },
        merge=True,
    )

    db.collection("link_codes").document(code_doc.id).update(
        {
            "used": True,
            "used_by": user_id,
            "used_at": now_iso(),
            "failed_attempts": 0,
        }
    )

    return {"success": True, "caretaker_id": caretaker_id, "user_id": user_id, "link_id": link_id}


def register_failed_code_attempt(code: str) -> None:
    normalized_code = _normalize_code(code)
    if not normalized_code:
        return
    code_doc = _find_code_doc(normalized_code)
    if not code_doc:
        return
    data = code_doc.to_dict() or {}
    attempts = int(data.get("failed_attempts", 0)) + 1
    locked = attempts >= max(3, settings.LINK_CODE_MAX_ATTEMPTS)
    db.collection("link_codes").document(code_doc.id).update(
        {
            "failed_attempts": attempts,
            "locked": locked,
            "last_failed_at": now_iso(),
        }
    )


def get_caretaker_for_user(user_id: str) -> Optional[str]:
    links = (
        db.collection("care_links")
        .where("user_id", "==", user_id)
        .where("active", "==", True)
        .limit(1)
        .stream()
    )
    for doc in links:
        data = doc.to_dict() or {}
        caretaker_id = data.get("caretaker_id")
        if caretaker_id:
            return caretaker_id
    user = db.collection("users").document(user_id).get()
    if user.exists:
        return (user.to_dict() or {}).get("caretaker_id")
    return None


def get_users_for_caretaker(caretaker_id: str) -> List[str]:
    linked_users: List[str] = []
    links = (
        db.collection("care_links")
        .where("caretaker_id", "==", caretaker_id)
        .where("active", "==", True)
        .stream()
    )
    for doc in links:
        data = doc.to_dict() or {}
        user_id = data.get("user_id")
        if user_id:
            linked_users.append(user_id)
    return linked_users
