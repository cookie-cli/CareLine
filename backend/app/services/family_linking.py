from __future__ import annotations

from datetime import datetime, timedelta
import random
import string
from typing import Any, Dict, List, Optional

from firebase_admin import firestore

from app.database.firebase import db


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def _generate_link_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def create_caretaker_link_code(caretaker_id: str, expires_minutes: int = 30) -> Dict[str, Any]:
    code = _generate_link_code()
    expires_at = (datetime.utcnow() + timedelta(minutes=expires_minutes)).isoformat()

    payload = {
        "code": code,
        "caretaker_id": caretaker_id,
        "created_at": now_iso(),
        "expires_at": expires_at,
        "used": False,
        "used_by": None,
    }
    db.collection("link_codes").document(code).set(payload)
    return payload


def connect_user_with_code(user_id: str, code: str) -> Dict[str, Any]:
    code_doc = db.collection("link_codes").document(code.upper()).get()
    if not code_doc.exists:
        return {"success": False, "error": "Invalid code"}

    code_data = code_doc.to_dict() or {}
    if code_data.get("used"):
        return {"success": False, "error": "Code already used"}

    expires_at = code_data.get("expires_at")
    if expires_at and datetime.fromisoformat(expires_at) < datetime.utcnow():
        return {"success": False, "error": "Code expired"}

    caretaker_id = code_data.get("caretaker_id")
    if not caretaker_id:
        return {"success": False, "error": "Code data invalid"}

    link_id = f"{caretaker_id}_{user_id}"
    link_payload = {
        "caretaker_id": caretaker_id,
        "user_id": user_id,
        "active": True,
        "created_at": now_iso(),
        "source": "invite_code",
        "code": code.upper(),
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

    db.collection("link_codes").document(code.upper()).update(
        {
            "used": True,
            "used_by": user_id,
            "used_at": now_iso(),
        }
    )

    return {"success": True, "caretaker_id": caretaker_id, "user_id": user_id, "link_id": link_id}


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

