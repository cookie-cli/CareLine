from fastapi import APIRouter, HTTPException, Query

from app.database.firebase import db
from app.services.family_linking import (
    connect_user_with_code,
    create_caretaker_link_code,
    get_caretaker_for_user,
    get_users_for_caretaker,
)

router = APIRouter(prefix="/linking", tags=["linking"])


@router.post("/create-code")
def create_code(
    caretaker_id: str,
    expires_minutes: int = Query(default=30, ge=5, le=1440),
):
    payload = create_caretaker_link_code(caretaker_id=caretaker_id, expires_minutes=expires_minutes)
    return {
        "success": True,
        "caretaker_id": caretaker_id,
        "code": payload["code"],
        "expires_at": payload["expires_at"],
    }


@router.post("/connect")
def connect_user(
    user_id: str,
    code: str,
):
    result = connect_user_with_code(user_id=user_id, code=code)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unable to connect"))
    return result


@router.get("/caretaker/{caretaker_id}/users")
def caretaker_users(caretaker_id: str):
    users = get_users_for_caretaker(caretaker_id)
    return {
        "success": True,
        "caretaker_id": caretaker_id,
        "users": users,
        "count": len(users),
    }


@router.get("/user/{user_id}/caretaker")
def user_caretaker(user_id: str):
    caretaker_id = get_caretaker_for_user(user_id)
    if not caretaker_id:
        raise HTTPException(status_code=404, detail="User is not linked to a caretaker")
    caretaker = db.collection("users").document(caretaker_id).get()
    return {
        "success": True,
        "user_id": user_id,
        "caretaker_id": caretaker_id,
        "caretaker_profile": caretaker.to_dict() if caretaker.exists else {},
    }

