from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.database.firebase import db
from app.services.realtime import realtime_hub
from app.services.prescription_schedule import TIME_BUCKETS, aggregate_expected_schedule, expected_schedule_from_prescription


def today_str() -> str:
    return date.today().isoformat()


def _empty_bucket_status() -> Dict[str, Dict[str, Any]]:
    return {
        "morning": {"status": "pending", "nudge_id": None, "response": None},
        "afternoon": {"status": "pending", "nudge_id": None, "response": None},
        "night": {"status": "pending", "nudge_id": None, "response": None},
    }


def get_active_prescriptions_for_caretaker(caretaker_id: str) -> List[Dict[str, Any]]:
    docs = (
        db.collection("prescriptions")
        .where("caretaker_id", "==", caretaker_id)
        .where("status", "==", "active")
        .stream()
    )
    return [doc.to_dict() for doc in docs]


def expected_schedule_for_caretaker(caretaker_id: str, on_date: date) -> Dict[str, List[str]]:
    prescriptions = get_active_prescriptions_for_caretaker(caretaker_id)
    return aggregate_expected_schedule(prescriptions, on_date)


def get_active_prescriptions_for_user(user_id: str) -> List[Dict[str, Any]]:
    docs = (
        db.collection("prescriptions")
        .where("user_id", "==", user_id)
        .where("status", "==", "active")
        .stream()
    )
    return [doc.to_dict() for doc in docs]


def expected_schedule_for_user(user_id: str, on_date: date) -> Dict[str, List[str]]:
    prescriptions = get_active_prescriptions_for_user(user_id)
    return aggregate_expected_schedule(prescriptions, on_date)


def _parse_nudge_status(data: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
    return {
        "status": "taken" if data.get("status") == "acknowledged" else "pending",
        "nudge_id": doc_id,
        "response": data.get("response"),
        "type": data.get("type", "medicine_reminder"),
        "target_role": data.get("target_role", "user"),
    }


def get_today_bucket_status(
    caretaker_id: str,
    for_date: str,
    target_role: str = "user",
) -> Dict[str, Dict[str, Any]]:
    status = _empty_bucket_status()
    docs = (
        db.collection("nudges")
        .where("caretaker_id", "==", caretaker_id)
        .where("date", "==", for_date)
        .stream()
    )

    for doc in docs:
        data = doc.to_dict() or {}
        bucket = data.get("time_bucket")
        if bucket not in status:
            continue

        role = data.get("target_role")
        if not role:
            role = "user"

        if role != target_role:
            continue

        if data.get("type") not in {"medicine_reminder", "caretaker_action", "caretaker_ping"}:
            continue

        status[bucket] = _parse_nudge_status(data, doc.id)
    return status


def get_today_bucket_status_for_user(user_id: str, for_date: str) -> Dict[str, Dict[str, Any]]:
    status = _empty_bucket_status()
    docs = (
        db.collection("nudges")
        .where("user_id", "==", user_id)
        .where("date", "==", for_date)
        .stream()
    )
    for doc in docs:
        data = doc.to_dict() or {}
        bucket = data.get("time_bucket")
        if bucket not in status:
            continue
        if data.get("target_role") != "user":
            continue
        if data.get("type") not in {"medicine_reminder"}:
            continue
        status[bucket] = _parse_nudge_status(data, doc.id)
    return status


def _existing_nudge_keys(caretaker_id: str, for_date: str) -> set[Tuple[str, str, str]]:
    docs = (
        db.collection("nudges")
        .where("caretaker_id", "==", caretaker_id)
        .where("date", "==", for_date)
        .stream()
    )
    keys: set[Tuple[str, str, str]] = set()
    for doc in docs:
        data = doc.to_dict() or {}
        bucket = data.get("time_bucket")
        if bucket not in TIME_BUCKETS:
            continue
        target = data.get("target_role", "user")
        ntype = data.get("type", "medicine_reminder")
        keys.add((bucket, target, ntype))
    return keys


def _create_user_nudge(
    caretaker_id: str,
    user_id: str,
    for_date: str,
    bucket: str,
    meds_preview: str,
    prescription_id: str | None = None,
) -> str:
    payload = {
        "type": "medicine_reminder",
        "target_role": "user",
        "caretaker_id": caretaker_id,
        "user_id": user_id,
        "time_bucket": bucket,
        "message": f"Did you take your {bucket} medicine? {meds_preview}".strip(),
        "status": "pending",
        "date": for_date,
        "created_at": datetime.utcnow().isoformat(),
        "acknowledged_at": None,
        "actions": ["taken", "skipped", "call_caretaker"],
    }
    if prescription_id:
        payload["prescription_id"] = prescription_id
    ref = db.collection("nudges").add(payload)
    nudge_id = ref[1].id
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(realtime_hub.emit_nudge_event("created", {**payload, "nudge_id": nudge_id}))
    except RuntimeError:
        pass
    return nudge_id


def _create_caretaker_action_nudge(
    caretaker_id: str,
    user_id: str,
    for_date: str,
    bucket: str,
    meds_preview: str,
    user_nudge_id: str,
    kind: str = "caretaker_action",
) -> str:
    payload = {
        "type": kind,
        "target_role": "caretaker",
        "caretaker_id": caretaker_id,
        "user_id": user_id,
        "time_bucket": bucket,
        "message": f"Please remind user for {bucket} medicines. {meds_preview}".strip(),
        "status": "pending",
        "date": for_date,
        "created_at": datetime.utcnow().isoformat(),
        "acknowledged_at": None,
        "actions": ["checked", "remind_user", "call_user"],
        "linked_user_nudge_id": user_nudge_id,
    }
    ref = db.collection("nudges").add(payload)
    nudge_id = ref[1].id
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(realtime_hub.emit_nudge_event("created", {**payload, "nudge_id": nudge_id}))
    except RuntimeError:
        pass
    return nudge_id


def ensure_daily_medicine_nudges(
    caretaker_id: str,
    user_id: str | None,
    for_date: str,
    expected_schedule: Dict[str, List[str]],
    prescription_id: str | None = None,
) -> Dict[str, Any]:
    # Self-care mode: user is also the caretaker.
    if not user_id:
        user_id = caretaker_id

    existing = _existing_nudge_keys(caretaker_id, for_date)
    created: List[Dict[str, str]] = []

    for bucket in TIME_BUCKETS:
        if not expected_schedule.get(bucket):
            continue

        meds_preview = ", ".join(expected_schedule.get(bucket, [])[:3])

        user_key = (bucket, "user", "medicine_reminder")
        user_nudge_id = None
        if user_key not in existing:
            user_nudge_id = _create_user_nudge(
                caretaker_id=caretaker_id,
                user_id=user_id,
                for_date=for_date,
                bucket=bucket,
                meds_preview=meds_preview,
                prescription_id=prescription_id,
            )
            created.append({"bucket": bucket, "target_role": "user", "nudge_id": user_nudge_id})
            existing.add(user_key)

        # Extra nudge only when a separate caretaker exists.
        if caretaker_id and user_id and caretaker_id != user_id:
            caretaker_key = (bucket, "caretaker", "caretaker_action")
            if caretaker_key not in existing:
                if not user_nudge_id:
                    user_nudge_id = _get_user_nudge_id(caretaker_id, for_date, bucket)
                caretaker_nudge_id = _create_caretaker_action_nudge(
                    caretaker_id=caretaker_id,
                    user_id=user_id,
                    for_date=for_date,
                    bucket=bucket,
                    meds_preview=meds_preview,
                    user_nudge_id=user_nudge_id or "",
                    kind="caretaker_action",
                )
                created.append({"bucket": bucket, "target_role": "caretaker", "nudge_id": caretaker_nudge_id})
                existing.add(caretaker_key)

    return {
        "created_count": len(created),
        "created": created,
        "existing_keys": [f"{b}:{r}:{t}" for (b, r, t) in sorted(existing)],
    }


def _get_user_nudge_id(caretaker_id: str, for_date: str, bucket: str) -> Optional[str]:
    docs = (
        db.collection("nudges")
        .where("caretaker_id", "==", caretaker_id)
        .where("date", "==", for_date)
        .where("time_bucket", "==", bucket)
        .where("target_role", "==", "user")
        .limit(1)
        .stream()
    )
    for doc in docs:
        return doc.id
    return None


def create_caretaker_escalation_nudges(caretaker_id: str, user_id: str, for_date: str) -> Dict[str, Any]:
    if caretaker_id == user_id:
        return {"created_count": 0, "created": []}

    docs = (
        db.collection("nudges")
        .where("caretaker_id", "==", caretaker_id)
        .where("date", "==", for_date)
        .where("target_role", "==", "user")
        .where("type", "==", "medicine_reminder")
        .stream()
    )

    created: List[Dict[str, str]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("status") == "acknowledged":
            continue
        bucket = data.get("time_bucket")
        if bucket not in TIME_BUCKETS:
            continue

        existing = (
            db.collection("nudges")
            .where("caretaker_id", "==", caretaker_id)
            .where("date", "==", for_date)
            .where("type", "==", "caretaker_action")
            .where("linked_user_nudge_id", "==", doc.id)
            .limit(1)
            .stream()
        )
        if any(True for _ in existing):
            continue

        nudge_id = _create_caretaker_action_nudge(
            caretaker_id=caretaker_id,
            user_id=user_id,
            for_date=for_date,
            bucket=bucket,
            meds_preview="",
            user_nudge_id=doc.id,
            kind="caretaker_action",
        )
        created.append({"bucket": bucket, "target_role": "caretaker", "nudge_id": nudge_id})

    return {"created_count": len(created), "created": created}


def ensure_daily_nudges_for_prescription(
    prescription_data: Dict[str, Any],
    prescription_id: str,
    for_date: str,
) -> Dict[str, Any]:
    caretaker_id = prescription_data.get("caretaker_id")
    user_id = prescription_data.get("user_id")
    if not user_id:
        return {"created_count": 0, "created": [], "skipped": "missing_user_id"}

    if not caretaker_id:
        caretaker_id = user_id

    day = date.fromisoformat(for_date)
    expected = expected_schedule_from_prescription(prescription_data, day)
    result = ensure_daily_medicine_nudges(
        caretaker_id=caretaker_id,
        user_id=user_id,
        for_date=for_date,
        expected_schedule=expected,
        prescription_id=prescription_id,
    )

    escalation = create_caretaker_escalation_nudges(caretaker_id, user_id, for_date)
    result["caretaker_escalation"] = escalation
    return result
