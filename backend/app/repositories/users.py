from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from app.database.firebase import db


class UserRepository:
    def get_by_id(self, user_id: str) -> Dict[str, Any] | None:
        doc = db.collection("users").document(user_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["id"] = doc.id
        return data

    def upsert(self, user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        doc_ref = db.collection("users").document(user_id)
        existing = doc_ref.get()

        payload: Dict[str, Any] = {
            **fields,
            "updated_at": now,
        }
        if not existing.exists:
            payload.setdefault("created_at", now)
            payload.setdefault("role", "user")

        doc_ref.set(payload, merge=True)
        doc = doc_ref.get()
        data = doc.to_dict() or {}
        data["id"] = doc.id
        return data


user_repo = UserRepository()
