from __future__ import annotations

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


user_repo = UserRepository()
