from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.database.firebase import db


class PrescriptionRepository:
    def list_for_admin(self, patient_name: Optional[str] = None) -> List[Dict[str, Any]]:
        query = db.collection("prescriptions").order_by("created_at", descending=True).stream()
        return self._collect_list(query, patient_name=patient_name)

    def list_for_caretaker(self, caretaker_id: str, patient_name: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            query = (
                db.collection("prescriptions")
                .where("caretaker_id", "==", caretaker_id)
                .order_by("created_at", descending=True)
                .stream()
            )
            return self._collect_list(query, patient_name=patient_name)
        except Exception:
            # Fallback when Firestore composite index is missing.
            query = (
                db.collection("prescriptions")
                .where("caretaker_id", "==", caretaker_id)
                .stream()
            )
            return self._collect_list(query, patient_name=patient_name, sort_created_desc=True)

    def list_for_user(self, user_id: str, patient_name: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            query = (
                db.collection("prescriptions")
                .where("user_id", "==", user_id)
                .order_by("created_at", descending=True)
                .stream()
            )
            return self._collect_list(query, patient_name=patient_name)
        except Exception:
            # Fallback when Firestore composite index is missing.
            query = (
                db.collection("prescriptions")
                .where("user_id", "==", user_id)
                .stream()
            )
            return self._collect_list(query, patient_name=patient_name, sort_created_desc=True)

    def get_by_id(self, doc_id: str) -> Dict[str, Any] | None:
        doc = db.collection("prescriptions").document(doc_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["id"] = doc.id
        return data

    def list_expiring_active(self, today_iso: str, warning_iso: str) -> List[Dict[str, Any]]:
        docs = (
            db.collection("prescriptions")
            .where("expiry_date", "<=", warning_iso)
            .where("expiry_date", ">=", today_iso)
            .where("status", "==", "active")
            .where("expiry_alert_sent", "!=", True)
            .stream()
        )
        records: List[Dict[str, Any]] = []
        for doc in docs:
            data = doc.to_dict() or {}
            data["id"] = doc.id
            records.append(data)
        return records

    def mark_expiry_alert_sent(self, prescription_id: str) -> None:
        db.collection("prescriptions").document(prescription_id).update({"expiry_alert_sent": True})

    @staticmethod
    def _collect_list(
        query,
        patient_name: Optional[str],
        sort_created_desc: bool = False,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for doc in query:
            payload = doc.to_dict() or {}
            if patient_name and payload.get("patient_name") != patient_name:
                continue
            payload["id"] = doc.id
            results.append(payload)
        if sort_created_desc:
            results.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return results


prescription_repo = PrescriptionRepository()
