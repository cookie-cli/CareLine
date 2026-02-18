from __future__ import annotations

from typing import Any, Dict, List

from app.database.firebase import db


class NudgeRepository:
    def create(self, payload: Dict[str, Any]) -> str:
        ref = db.collection("nudges").add(payload)
        return ref[1].id

    def get_by_id(self, nudge_id: str) -> Dict[str, Any] | None:
        doc = db.collection("nudges").document(nudge_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["nudge_id"] = doc.id
        return data

    def update(self, nudge_id: str, payload: Dict[str, Any]) -> None:
        db.collection("nudges").document(nudge_id).update(payload)

    def list_for_caretaker_on_date(self, caretaker_id: str, date_filter: str) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where("caretaker_id", "==", caretaker_id)
            .where("date", "==", date_filter)
            .stream()
        )
        return self._to_list(docs, id_field="nudge_id")

    def list_for_user_on_date(self, user_id: str, date_filter: str) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where("user_id", "==", user_id)
            .where("date", "==", date_filter)
            .stream()
        )
        return self._to_list(docs, id_field="nudge_id")

    def list_pending_expiry_alerts(self, caretaker_id: str) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where("caretaker_id", "==", caretaker_id)
            .where("type", "==", "expiry_alert")
            .where("status", "==", "pending")
            .stream()
        )
        return self._to_list(docs, id_field="nudge_id")

    def list_before_date(self, before_date: str, limit: int) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where("date", "<", before_date)
            .limit(limit)
            .stream()
        )
        return self._to_list(docs, id_field="id")

    def delete_by_ids(self, nudge_ids: List[str]) -> int:
        if not nudge_ids:
            return 0
        deleted = 0
        batch = db.batch()
        batch_size = 0

        for nudge_id in nudge_ids:
            ref = db.collection("nudges").document(nudge_id)
            batch.delete(ref)
            batch_size += 1
            if batch_size >= 450:
                batch.commit()
                deleted += batch_size
                batch = db.batch()
                batch_size = 0

        if batch_size > 0:
            batch.commit()
            deleted += batch_size
        return deleted

    @staticmethod
    def add_call_log(payload: Dict[str, Any]) -> str:
        ref = db.collection("call_logs").add(payload)
        return ref[1].id

    @staticmethod
    def _to_list(docs, id_field: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for doc in docs:
            data = doc.to_dict() or {}
            data[id_field] = doc.id
            items.append(data)
        return items


nudge_repo = NudgeRepository()
