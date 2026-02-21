from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.repositories import nudge_repo, prescription_repo, user_repo
from app.security import (
    AuthUser,
    authenticate_token,
    can_access_nudge,
    can_access_prescription,
    can_access_user,
    ensure_caretaker_access,
    ensure_user_access,
    get_current_user,
    rate_limit,
    require_admin,
)
from app.services.family_linking import get_caretaker_for_user
from app.services.nudges_engine import (
    ensure_daily_medicine_nudges,
    expected_schedule_for_user,
    get_today_bucket_status,
    get_today_bucket_status_for_user,
)
from app.services.realtime import realtime_hub

router = APIRouter(
    prefix="/nudges",
    tags=["nudges"],
    dependencies=[Depends(get_current_user)],
)

TimeBucket = Literal["morning", "afternoon", "night"]


def today_str() -> str:
    return date.today().isoformat()


@router.websocket("/ws")
async def nudges_websocket(websocket: WebSocket):
    token = (websocket.query_params.get("token") or "").strip()
    auth_header = (websocket.headers.get("authorization") or "").strip()
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return

    try:
        current_user = authenticate_token(token)
    except HTTPException:
        await websocket.close(code=1008, reason="Invalid token")
        return

    rooms = [f"user:{current_user.user_id}"]
    if current_user.role in {"caretaker", "admin"}:
        rooms.append(f"caretaker:{current_user.user_id}")

    await websocket.accept()
    for room in rooms:
        realtime_hub.connect(room, websocket)

    await websocket.send_json(
        {
            "type": "connected",
            "rooms": rooms,
            "user_id": current_user.user_id,
            "role": current_user.role,
        }
    )

    try:
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        for room in rooms:
            realtime_hub.disconnect(room, websocket)


def check_expiring_prescriptions():
    today = date.today()
    today_iso = today_str()
    warning_date = (today + timedelta(days=7)).isoformat()
    docs = prescription_repo.list_expiring_active(today_iso=today_iso, warning_iso=warning_date)
    alerts_sent = []

    for doc in docs:
        caretaker_id = doc.get("caretaker_id")
        user_id = doc.get("user_id") or doc.get("added_by")
        medicine_name = doc.get("medicine_name", "Medicine")
        expiry_date = doc.get("expiry_date")
        doctor_phone = doc.get("doctor_phone")

        nudge_data = {
            "type": "expiry_alert",
            "target_role": "caretaker",
            "user_id": user_id,
            "caretaker_id": caretaker_id,
            "prescription_id": doc["id"],
            "medicine_name": medicine_name,
            "expiry_date": expiry_date,
            "message": f"Reminder: {medicine_name} expires on {expiry_date}. Consult doctor?",
            "status": "pending",
            "date": today_str(),
            "created_at": datetime.utcnow().isoformat(),
            "actions": ["call_doctor", "mark_done", "snooze"],
            "doctor_phone": doctor_phone,
        }

        nudge_id = nudge_repo.create(nudge_data)
        prescription_repo.mark_expiry_alert_sent(doc["id"])
        alerts_sent.append(
            {
                "nudge_id": nudge_id,
                "medicine": medicine_name,
                "caretaker_id": caretaker_id,
            }
        )

    return {"alerts_sent": len(alerts_sent), "details": alerts_sent}


@router.post("/check-expiry-alerts")
async def trigger_expiry_check(
    _: AuthUser = Depends(require_admin),
    __: None = Depends(rate_limit("nudges-check-expiry", limit=10)),
):
    result = check_expiring_prescriptions()
    return {
        "success": True,
        "checked_at": datetime.utcnow().isoformat(),
        **result,
    }


@router.post("/call-doctor")
async def initiate_doctor_call(
    prescription_id: str,
    nudge_id: Optional[str] = None,
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("nudges-call-doctor", limit=20)),
):
    pres_data = prescription_repo.get_by_id(prescription_id)
    if not pres_data:
        raise HTTPException(404, "Prescription not found")

    if not can_access_prescription(current_user, pres_data):
        raise HTTPException(status_code=403, detail="Forbidden")
    doctor_phone = pres_data.get("doctor_phone")
    doctor_name = pres_data.get("doctor_name", "Doctor")

    if not doctor_phone:
        caretaker_id = pres_data.get("caretaker_id")
        caretaker_data = user_repo.get_by_id(caretaker_id) or {}
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
    nudge_repo.add_call_log(call_log)

    if nudge_id:
        nudge_repo.update(
            nudge_id,
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
async def get_doctor_info(
    prescription_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    data = prescription_repo.get_by_id(prescription_id)
    if not data:
        raise HTTPException(404, "Prescription not found")
    if not can_access_prescription(current_user, data):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {
        "doctor_name": data.get("doctor_name"),
        "doctor_phone": data.get("doctor_phone"),
        "clinic_name": data.get("clinic_name"),
        "consultation_date": data.get("consultation_date"),
    }


@router.post("/send")
async def send_nudge(
    user_id: str,
    caretaker_id: str,
    time_bucket: TimeBucket,
    message: Optional[str] = None,
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("nudges-send", limit=30)),
):
    ensure_caretaker_access(current_user, caretaker_id)
    if not can_access_user(current_user, user_id):
        raise HTTPException(status_code=403, detail="Forbidden")

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

    nudge_id = nudge_repo.create(nudge_data)
    return {
        "success": True,
        "nudge_id": nudge_id,
        "nudge": nudge_data,
    }


@router.post("/respond")
async def respond_to_nudge(
    nudge_id: str,
    response: Literal[
        "taken",
        "skipped",
        "call_user",
        "checked",
        "remind_user",
        "call_caretaker",
    ] = "taken",
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("nudges-respond", limit=60)),
):
    data = nudge_repo.get_by_id(nudge_id)
    if not data:
        raise HTTPException(status_code=404, detail="Nudge not found")
    if not can_access_nudge(current_user, data):
        raise HTTPException(status_code=403, detail="Forbidden")
    update_data = {
        "status": "acknowledged",
        "response": response,
        "acknowledged_at": datetime.utcnow().isoformat(),
    }
    nudge_repo.update(nudge_id, update_data)

    if response == "call_user":
        user_id = data.get("user_id")
        user_data = user_repo.get_by_id(user_id) or {}
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
        ping_nudge_id = nudge_repo.create(user_ping)
        return {
            "success": True,
            "nudge_id": nudge_id,
            "update": update_data,
            "user_ping_nudge_id": ping_nudge_id,
        }

    if response == "call_caretaker":
        caretaker_id = data.get("caretaker_id")
        caretaker_data = user_repo.get_by_id(caretaker_id) or {}
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
async def get_today_status(
    caretaker_id: str = Query(..., description="Caretaker user id"),
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_caretaker_access(current_user, caretaker_id)
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
async def get_today_status_user(
    user_id: str = Query(..., description="User id"),
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_user_access(current_user, user_id)
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
async def sync_daily_nudges(
    caretaker_id: str,
    user_id: str = "",
    for_date: str = Query(default_factory=today_str),
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("nudges-sync-daily", limit=30)),
):
    ensure_caretaker_access(current_user, caretaker_id)
    if user_id and not can_access_user(current_user, user_id):
        raise HTTPException(status_code=403, detail="Forbidden")

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
async def user_tick_reminder(
    nudge_id: str,
    action: Literal["taken", "skipped", "call_caretaker"] = "taken",
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("nudges-user-tick", limit=60)),
):
    return respond_to_nudge(nudge_id=nudge_id, response=action, current_user=current_user)


@router.post("/caretaker-tick")
async def caretaker_tick_reminder(
    nudge_id: str,
    action: Literal["checked", "remind_user", "call_user"] = "checked",
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("nudges-caretaker-tick", limit=60)),
):
    return respond_to_nudge(nudge_id=nudge_id, response=action, current_user=current_user)


@router.get("/inbox/caretaker")
async def caretaker_inbox(
    caretaker_id: str = Query(...),
    date_filter: str = Query(default_factory=today_str),
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_caretaker_access(current_user, caretaker_id)
    docs = nudge_repo.list_for_caretaker_on_date(caretaker_id=caretaker_id, date_filter=date_filter)
    items = []
    for doc in docs:
        if doc.get("target_role", "caretaker") != "caretaker":
            continue
        items.append(doc)
    return {"success": True, "role": "caretaker", "count": len(items), "nudges": items}


@router.get("/inbox/user")
async def user_inbox(
    user_id: str = Query(...),
    date_filter: str = Query(default_factory=today_str),
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_user_access(current_user, user_id)
    docs = nudge_repo.list_for_user_on_date(user_id=user_id, date_filter=date_filter)
    items = []
    for doc in docs:
        if doc.get("target_role") != "user":
            continue
        items.append(doc)
    return {"success": True, "role": "user", "count": len(items), "nudges": items}


@router.get("/expiry-alerts")
async def get_expiry_alerts(
    caretaker_id: str = Query(...),
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_caretaker_access(current_user, caretaker_id)
    alerts = nudge_repo.list_pending_expiry_alerts(caretaker_id=caretaker_id)

    return {
        "caretaker_id": caretaker_id,
        "pending_alerts": len(alerts),
        "alerts": alerts,
    }


@router.delete("/cleanup-old")
async def cleanup_old_nudges(
    before_date: str = Query(default_factory=today_str),
    limit: int = Query(500, ge=1, le=1000),
    dry_run: bool = Query(True),
    confirm: str = Query(""),
    _: AuthUser = Depends(require_admin),
    __: None = Depends(rate_limit("nudges-cleanup", limit=5)),
):
    try:
        date.fromisoformat(before_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid before_date. Use YYYY-MM-DD")

    docs = nudge_repo.list_before_date(before_date=before_date, limit=limit)

    preview = []
    for doc in docs[:20]:
        preview.append(
            {
                "id": doc.get("id"),
                "date": doc.get("date"),
                "caretaker_id": doc.get("caretaker_id"),
                "time_bucket": doc.get("time_bucket"),
                "type": doc.get("type", "medicine_reminder"),
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

    deleted = nudge_repo.delete_by_ids([doc.get("id", "") for doc in docs if doc.get("id")])

    return {
        "success": True,
        "mode": "delete",
        "before_date": before_date,
        "deleted_count": deleted,
    }


@router.get("/health")
async def nudges_health():
    return {
        "nudges": "ok",
        "expiry_alerts": "enabled",
        "calling": "enabled",
        "date": today_str(),
    }
