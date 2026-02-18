from fastapi import APIRouter, Depends, HTTPException, Query

from app.repositories import user_repo
from app.security import (
    AuthUser,
    ensure_caretaker_access,
    ensure_user_access,
    get_current_user,
    rate_limit,
    require_roles,
)
from app.services.family_linking import (
    extract_code_from_qr_payload,
    connect_user_with_code,
    create_caretaker_link_code,
    get_caretaker_for_user,
    get_users_for_caretaker,
    register_failed_code_attempt,
)

router = APIRouter(
    prefix="/linking",
    tags=["linking"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/create-code")
def create_code(
    caretaker_id: str,
    expires_minutes: int = Query(default=30, ge=5, le=1440),
    current_user: AuthUser = Depends(require_roles("caretaker", "admin")),
    _: None = Depends(rate_limit("linking-create-code", limit=10)),
):
    ensure_caretaker_access(current_user, caretaker_id)
    payload = create_caretaker_link_code(caretaker_id=caretaker_id, expires_minutes=expires_minutes)
    return {
        "success": True,
        "caretaker_id": caretaker_id,
        "code": payload["code"],
        "expires_at": payload["expires_at"],
    }


@router.post("/create-qr")
def create_qr_code(
    caretaker_id: str,
    expires_minutes: int = Query(default=30, ge=5, le=1440),
    current_user: AuthUser = Depends(require_roles("caretaker", "admin")),
    _: None = Depends(rate_limit("linking-create-qr", limit=10)),
):
    ensure_caretaker_access(current_user, caretaker_id)
    payload = create_caretaker_link_code(caretaker_id=caretaker_id, expires_minutes=expires_minutes)
    return {
        "success": True,
        "caretaker_id": caretaker_id,
        "code": payload["code"],
        "expires_at": payload["expires_at"],
        "qr_payload": payload.get("qr_payload"),
        "link_url": payload.get("qr_payload"),
    }


@router.post("/connect")
def connect_user(
    user_id: str,
    code: str,
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("linking-connect", limit=8)),
):
    ensure_user_access(current_user, user_id)
    result = connect_user_with_code(user_id=user_id, code=code)
    if not result.get("success"):
        if "invalid" in str(result.get("error", "")).lower():
            register_failed_code_attempt(code)
        raise HTTPException(status_code=400, detail=result.get("error", "Unable to connect"))
    return result


@router.post("/connect-qr")
def connect_user_qr(
    user_id: str,
    qr_payload: str,
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("linking-connect-qr", limit=8)),
):
    ensure_user_access(current_user, user_id)
    code = extract_code_from_qr_payload(qr_payload)
    if not code:
        raise HTTPException(status_code=400, detail="Invalid QR payload")
    result = connect_user_with_code(user_id=user_id, code=code)
    if not result.get("success"):
        if "invalid" in str(result.get("error", "")).lower():
            register_failed_code_attempt(code)
        raise HTTPException(status_code=400, detail=result.get("error", "Unable to connect"))
    return result


@router.get("/caretaker/{caretaker_id}/users")
def caretaker_users(
    caretaker_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_caretaker_access(current_user, caretaker_id)
    users = get_users_for_caretaker(caretaker_id)
    return {
        "success": True,
        "caretaker_id": caretaker_id,
        "users": users,
        "count": len(users),
    }


@router.get("/user/{user_id}/caretaker")
def user_caretaker(
    user_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    ensure_user_access(current_user, user_id)
    caretaker_id = get_caretaker_for_user(user_id)
    if not caretaker_id:
        raise HTTPException(status_code=404, detail="User is not linked to a caretaker")
    caretaker = user_repo.get_by_id(caretaker_id)
    return {
        "success": True,
        "user_id": user_id,
        "caretaker_id": caretaker_id,
        "caretaker_profile": caretaker or {},
    }
