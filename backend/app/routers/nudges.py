from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from app.database.firebase import db
from app.services.family_linking import get_caretaker_for_user
from app.services.nudges_engine import (
    ensure_daily_medicine_nudges,
    expected_schedule_for_user,
    get_today_bucket_status,
    get_today_bucket_status_for_user,
)

router = APIRouter(prefix="/nudges", tags=["nudges"])

TimeBucket = Literal["morning", "afternoon", "night"]


def today_str() -> str:
    return date.today().isoformat()


def check_expiring_prescriptions():
    today = date.today()
    warning_date = (today + timedelta(days=7)).isoformat()

    query = (
        db.collection("prescriptions")
        .where("expiry_date", "<=", warning_date)
        .where("expiry_date", ">=", today_str())
        .where("status", "==", "active")
        .where("expiry_alert_sent", "!=", True)
    )

    docs = list(query.stream())
    alerts_sent = []

    for doc in docs:
        data = doc.to_dict() or {}
        caretaker_id = data.get("caretaker_id")
        user_id = data.get("user_id") or data.get("added_by")
        medicine_name = data.get("medicine_name", "Medicine")
        expiry_date = data.get("expiry_date")
        doctor_phone = data.get("doctor_phone")

        nudge_data = {
            "type": "expiry_alert",
            "target_role": "caretaker",
            "user_id": user_id,
            "caretaker_id": caretaker_id,
            "prescription_id": doc.id,
            "medicine_name": medicine_name,
            "expiry_date": expiry_date,
            "message": f"Reminder: {medicine_name} expires on {expiry_date}. Consult doctor?",
            "status": "pending",
            "date": today_str(),
            "created_at": datetime.utcnow().isoformat(),
            "actions": ["call_doctor", "mark_done", "snooze"],
            "doctor_phone": doctor_phone,
        }

        nudge_ref = db.collection("nudges").add(nudge_data)
        doc.reference.update({"expiry_alert_sent": True})
        alerts_sent.append(
            {
                "nudge_id": nudge_ref[1].id,
                "medicine": medicine_name,
                "caretaker_id": caretaker_id,
            }
        )

    return {"alerts_sent": len(alerts_sent), "details": alerts_sent}


@router.post("/check-expiry-alerts")
def trigger_expiry_check():
    result = check_expiring_prescriptions()
    return {
        "success": True,
        "checked_at": datetime.utcnow().isoformat(),
        **result,
    }


@router.post("/call-doctor")
def initiate_doctor_call(
    prescription_id: str,
    nudge_id: Optional[str] = None,
):
    pres_ref = db.collection("prescriptions").document(prescription_id)
    pres = pres_ref.get()

    if not pres.exists:
        raise HTTPException(404, "Prescription not found")

    pres_data = pres.to_dict() or {}
    doctor_phone = pres_data.get("doctor_phone")
    doctor_name = pres_data.get("doctor_name", "Doctor")

    if not doctor_phone:
        caretaker_id = pres_data.get("caretaker_id")
        caretaker = db.collection("users").document(caretaker_id).get()
        caretaker_data = caretaker.to_dict() or {}
        doctor_phone = caretaker_data.get("default_doctor_phone")
        doctor_name = caretaker_data.get("default_doctor_name", "Doctor")

    if not doctor_phone:
        raise HTTPException(400, "No doctor phone number saved")

    clean_phone = doctor_phone.replace(" ", "").replace("-", "")
    if not clean_phone.startswith("+"):
        clean_phone = "+91" + clean_phone

    call_log = {
        "prescription_id": prescription_id,
        "nudge_id": nudge_id,
        "caretaker_id": pres_data.get("caretaker_id"),
        "doctor_phone": clean_phone,
        "doctor_name": doctor_name,
        "initiated_at": datetime.utcnow().isoformat(),
        "status": "initiated",
    }
    db.collection("call_logs").add(call_log)

    if nudge_id:
        db.collection("nudges").document(nudge_id).update(
            {
                "call_initiated": True,
                "call_initiated_at": datetime.utcnow().isoformat(),
            }
        )

    return {
        "success": True,
        "action": "dial",
        "doctor_name": doctor_name,
        "phone_number": clean_phone,
        "tel_url": f"tel:{clean_phone}",
        "message": f"Calling {doctor_name}...",
    }


@router.get("/doctor-info/{prescription_id}")
def get_doctor_info(prescription_id: str):
    pres = db.collection("prescriptions").document(prescription_id).get()
    if not pres.exists:
        raise HTTPException(404, "Prescription not found")

    data = pres.to_dict() or {}
    return {
        "doctor_name": data.get("doctor_name"),
        "doctor_phone": data.get("doctor_phone"),
        "clinic_name": data.get("clinic_name"),
        "consultation_date": data.get("consultation_date"),
    }


@router.post("/send")
def send_nudge(
    user_id: str,
    caretaker_id: str,
    time_bucket: TimeBucket,
    message: Optional[str] = None,
):
    nudge_data = {
        "type": "medicine_reminder",
        "target_role": "user",
        "user_id": user_id,
        "caretaker_id": caretaker_id,
        "time_bucket": time_bucket,
        "message": message or f"Did you take your {time_bucket} medicine?",
        "status": "pending",
        "date": today_str(),
        "created_at": datetime.utcnow().isoformat(),
        "acknowledged_at": None,
        "actions": ["taken", "skipped", "call_caretaker"],
    }

    doc_ref = db.collection("nudges").add(nudge_data)
    return {
        "success": True,
        "nudge_id": doc_ref[1].id,
        "nudge": nudge_data,
    }


@router.post("/respond")
def respond_to_nudge(
    nudge_id: str,
    response: Literal[
        "taken",
        "skipped",
        "call_user",
        "checked",
        "remind_user",
        "call_caretaker",
    ] = "taken",
):
    doc_ref = db.collection("nudges").document(nudge_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Nudge not found")

    data = doc.to_dict() or {}
    update_data = {
        "status": "acknowledged",
        "response": response,
        "acknowledged_at": datetime.utcnow().isoformat(),
    }
    doc_ref.update(update_data)

    if response == "call_user":
        user_id = data.get("user_id")
        user = db.collection("users").document(user_id).get()
        user_data = user.to_dict() or {}
        return {
            "success": True,
            "nudge_id": nudge_id,
            "update": update_data,
            "call_action": {
                "phone": user_data.get("phone"),
                "tel_url": f"tel:{user_data.get('phone')}",
            },
        }

    if response == "remind_user":
        user_ping = {
            "type": "caretaker_ping",
            "target_role": "user",
            "caretaker_id": data.get("caretaker_id"),
            "user_id": data.get("user_id"),
            "time_bucket": data.get("time_bucket"),
            "message": f"Your caretaker sent a reminder for {data.get('time_bucket', 'today')}.",
            "status": "pending",
            "date": today_str(),
            "created_at": datetime.utcnow().isoformat(),
            "actions": ["taken", "skipped", "call_caretaker"],
        }
        ping_ref = db.collection("nudges").add(user_ping)
        return {
            "success": True,
            "nudge_id": nudge_id,
            "update": update_data,
            "user_ping_nudge_id": ping_ref[1].id,
        }

    if response == "call_caretaker":
        caretaker_id = data.get("caretaker_id")
        caretaker = db.collection("users").document(caretaker_id).get()
        caretaker_data = caretaker.to_dict() or {}
        phone = caretaker_data.get("phone")
        return {
            "success": True,
            "nudge_id": nudge_id,
            "update": update_data,
            "call_action": {
                "phone": phone,
                "tel_url": f"tel:{phone}" if phone else "",
            },
        }

    return {
        "success": True,
        "nudge_id": nudge_id,
        "update": update_data,
    }


@router.get("/today-status")
def get_today_status(
    caretaker_id: str = Query(..., description="Caretaker user id"),
):
    today = today_str()
    user_status = get_today_bucket_status(caretaker_id, today, target_role="user")
    caretaker_tasks = get_today_bucket_status(caretaker_id, today, target_role="caretaker")
    return {
        "date": today,
        "caretaker_id": caretaker_id,
        "user_status": user_status,
        "caretaker_tasks": caretaker_tasks,
    }


@router.get("/today-status-user")
def get_today_status_user(
    user_id: str = Query(..., description="User id"),
):
    today = today_str()
    status = get_today_bucket_status_for_user(user_id, today)
    caretaker_id = get_caretaker_for_user(user_id)
    return {
        "date": today,
        "user_id": user_id,
        "caretaker_id": caretaker_id,
        "status": status,
    }


@router.post("/sync-daily")
def sync_daily_nudges(
    caretaker_id: str,
    user_id: str = "",
    for_date: str = Query(default_factory=today_str),
):
    try:
        day = date.fromisoformat(for_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid for_date. Use YYYY-MM-DD")

    resolved_user_id = user_id or caretaker_id
    expected = expected_schedule_for_user(resolved_user_id, day)
    result = ensure_daily_medicine_nudges(
        caretaker_id=caretaker_id,
        user_id=resolved_user_id,
        for_date=for_date,
        expected_schedule=expected,
    )

    return {
        "success": True,
        "date": for_date,
        "caretaker_id": caretaker_id,
        "user_id": resolved_user_id,
        "expected": expected,
        **result,
    }


@router.post("/user-tick")
def user_tick_reminder(
    nudge_id: str,
    action: Literal["taken", "skipped", "call_caretaker"] = "taken",
):
    return respond_to_nudge(nudge_id=nudge_id, response=action)


@router.post("/caretaker-tick")
def caretaker_tick_reminder(
    nudge_id: str,
    action: Literal["checked", "remind_user", "call_user"] = "checked",
):
    return respond_to_nudge(nudge_id=nudge_id, response=action)


@router.get("/inbox/caretaker")
def caretaker_inbox(caretaker_id: str = Query(...), date_filter: str = Query(default_factory=today_str)):
    docs = (
        db.collection("nudges")
        .where("caretaker_id", "==", caretaker_id)
        .where("date", "==", date_filter)
        .stream()
    )
    items = []
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("target_role", "caretaker") != "caretaker":
            continue
        items.append({"nudge_id": doc.id, **data})
    return {"success": True, "role": "caretaker", "count": len(items), "nudges": items}


@router.get("/inbox/user")
def user_inbox(user_id: str = Query(...), date_filter: str = Query(default_factory=today_str)):
    docs = (
        db.collection("nudges")
        .where("user_id", "==", user_id)
        .where("date", "==", date_filter)
        .stream()
    )
    items = []
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("target_role") != "user":
            continue
        items.append({"nudge_id": doc.id, **data})
    return {"success": True, "role": "user", "count": len(items), "nudges": items}


@router.get("/expiry-alerts")
def get_expiry_alerts(
    caretaker_id: str = Query(...),
):
    query = (
        db.collection("nudges")
        .where("caretaker_id", "==", caretaker_id)
        .where("type", "==", "expiry_alert")
        .where("status", "==", "pending")
    )

    alerts = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        alerts.append({"nudge_id": doc.id, **data})

    return {
        "caretaker_id": caretaker_id,
        "pending_alerts": len(alerts),
        "alerts": alerts,
    }


@router.delete("/cleanup-old")
def cleanup_old_nudges(
    before_date: str = Query(default_factory=today_str),
    limit: int = Query(500, ge=1, le=1000),
    dry_run: bool = Query(True),
    confirm: str = Query(""),
):
    try:
        date.fromisoformat(before_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid before_date. Use YYYY-MM-DD")

    docs = list(
        db.collection("nudges")
        .where("date", "<", before_date)
        .limit(limit)
        .stream()
    )

    preview = []
    for doc in docs[:20]:
        data = doc.to_dict() or {}
        preview.append(
            {
                "id": doc.id,
                "date": data.get("date"),
                "caretaker_id": data.get("caretaker_id"),
                "time_bucket": data.get("time_bucket"),
                "type": data.get("type", "medicine_reminder"),
            }
        )

    if dry_run:
        return {
            "success": True,
            "mode": "dry_run",
            "before_date": before_date,
            "matched_count": len(docs),
            "preview": preview,
        }

    if confirm != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Deletion blocked. Use dry_run=true or pass confirm=DELETE",
        )

    batch = db.batch()
    batch_size = 0
    deleted = 0

    for doc in docs:
        batch.delete(doc.reference)
        batch_size += 1

        if batch_size >= 450:
            batch.commit()
            deleted += batch_size
            batch = db.batch()
            batch_size = 0

    if batch_size > 0:
        batch.commit()
        deleted += batch_size

    return {
        "success": True,
        "mode": "delete",
        "before_date": before_date,
        "deleted_count": deleted,
    }


@router.get("/health")
def nudges_health():
    return {
        "nudges": "ok",
        "expiry_alerts": "enabled",
        "calling": "enabled",
        "date": today_str(),
    }
