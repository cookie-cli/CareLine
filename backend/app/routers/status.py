from datetime import date
from fastapi import APIRouter, Depends, Query

from app.security import AuthUser, ensure_caretaker_access, ensure_user_access, get_current_user
from app.services.family_linking import get_caretaker_for_user, get_users_for_caretaker
from app.services.nudges_engine import (
    ensure_daily_medicine_nudges,
    expected_schedule_for_user,
    get_today_bucket_status,
    get_today_bucket_status_for_user,
)

router = APIRouter(
    prefix="/status",
    tags=["status"],
    dependencies=[Depends(get_current_user)],
)


def today_date() -> date:
    return date.today()


def today_str() -> str:
    return today_date().isoformat()


@router.get("/today")
def get_today_status(
    caretaker_id: str = Query(..., description="Caretaker user id"),
    current_user: AuthUser = Depends(get_current_user),
):
    """
    Returns today's expected medicines + taken/pending status for caretaker.
    Works even when no linked user exists.
    """
    ensure_caretaker_access(current_user, caretaker_id)
    today = today_date()
    today_iso = today_str()
    users = get_users_for_caretaker(caretaker_id)
    user_id = users[0] if users else caretaker_id
    expected = expected_schedule_for_user(user_id, today)

    ensure_daily_medicine_nudges(
        caretaker_id=caretaker_id,
        user_id=user_id,
        for_date=today_iso,
        expected_schedule=expected,
    )
    user_nudge_status = get_today_bucket_status(caretaker_id, today_iso, target_role="user")
    caretaker_tasks = get_today_bucket_status(caretaker_id, today_iso, target_role="caretaker")

    status = {
        bucket: ("taken" if user_nudge_status[bucket]["status"] == "taken" else "pending")
        for bucket in ["morning", "afternoon", "night"]
    }

    return {
        "date": today_iso,
        "caretaker_id": caretaker_id,
        "user_id": user_id,
        "expected": expected,
        "status": status,
        "user_nudge_status": user_nudge_status,
        "caretaker_tasks": caretaker_tasks,
        "linked_users": users,
    }


@router.get("/caretaker-today")
def get_caretaker_today(
    caretaker_id: str = Query(..., description="Caretaker user id"),
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_caretaker_access(current_user, caretaker_id)
    data = get_today_status(caretaker_id, current_user)
    return {
        "date": data["date"],
        "role": "caretaker",
        "user_id": caretaker_id,
        "summary": data["status"],  # user's medicine completion
        "expected": data["expected"],
        "caretaker_tasks": data["caretaker_tasks"],
        "linked_users": data["linked_users"],
    }


@router.get("/user-today")
def get_user_today(
    user_id: str = Query(..., description="User id"),
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_user_access(current_user, user_id)
    today_iso = today_str()
    caretaker_id = get_caretaker_for_user(user_id)
    linked = True
    if not caretaker_id:
        # Self-care mode: user relies only on app reminders.
        caretaker_id = user_id
        linked = False

    expected = expected_schedule_for_user(user_id, today_date())
    ensure_daily_medicine_nudges(
        caretaker_id=caretaker_id,
        user_id=user_id,
        for_date=today_iso,
        expected_schedule=expected,
    )
    caretaker_status = get_today_bucket_status(caretaker_id, today_iso, target_role="caretaker")
    user_status = get_today_bucket_status_for_user(user_id, today_iso)

    return {
        "date": today_iso,
        "role": "user",
        "user_id": user_id,
        "linked": linked,
        "caretaker_id": caretaker_id,
        "expected_for_user": expected,
        "caretaker_status": caretaker_status,
        "user_status": user_status,
    }


@router.get("/health")
def status_health():
    return {
        "status": "ok",
        "date": today_str(),
    }
