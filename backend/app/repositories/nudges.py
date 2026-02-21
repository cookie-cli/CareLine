from __future__ import annotations

from typing import Any, Dict, List

from app.database.firebase import db
from app.services.realtime import realtime_hub
from firebase_admin import firestore


class NudgeRepository:
    def create(self, payload: Dict[str, Any]) -> str:
        ref = db.collection("nudges").add(payload)
        nudge_id = ref[1].id
        event_payload = {**payload, "nudge_id": nudge_id}
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(realtime_hub.emit_nudge_event("created", event_payload))
        except RuntimeError:
            # No active event loop (sync context/tests) - skip realtime emission.
            pass
        return nudge_id

    def get_by_id(self, nudge_id: str) -> Dict[str, Any] | None:
        doc = db.collection("nudges").document(nudge_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["nudge_id"] = doc.id
        return data

    def update(self, nudge_id: str, payload: Dict[str, Any]) -> None:
        doc_ref = db.collection("nudges").document(nudge_id)
        doc = doc_ref.get()
        existing = doc.to_dict() if doc.exists else {}
        doc_ref.update(payload)
        merged = {**(existing or {}), **payload, "nudge_id": nudge_id}
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(realtime_hub.emit_nudge_event("updated", merged))
        except RuntimeError:
            pass

    def list_for_caretaker_on_date(self, caretaker_id: str, date_filter: str) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where(filter=firestore.FieldFilter("caretaker_id", "==", caretaker_id))
            .where(filter=firestore.FieldFilter("date", "==", date_filter))
            .stream()
        )
        return self._to_list(docs, id_field="nudge_id")

    def list_for_user_on_date(self, user_id: str, date_filter: str) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .where(filter=firestore.FieldFilter("date", "==", date_filter))
            .stream()
        )
        return self._to_list(docs, id_field="nudge_id")

    def list_pending_expiry_alerts(self, caretaker_id: str) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where(filter=firestore.FieldFilter("caretaker_id", "==", caretaker_id))
            .where(filter=firestore.FieldFilter("type", "==", "expiry_alert"))
            .where(filter=firestore.FieldFilter("status", "==", "pending"))
            .stream()
        )
        return self._to_list(docs, id_field="nudge_id")

    def list_before_date(self, before_date: str, limit: int) -> List[Dict[str, Any]]:
        docs = (
            db.collection("nudges")
            .where(filter=firestore.FieldFilter("date", "<", before_date))
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
