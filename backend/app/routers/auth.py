from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends

from app.repositories import user_repo
from app.security import AuthUser, get_current_user, rate_limit

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/me")
def get_me(current_user: AuthUser = Depends(get_current_user)):
    profile = user_repo.get_by_id(current_user.user_id) or {}
    role = str(profile.get("role") or current_user.role or "user")
    caretaker_id = current_user.user_id if role == "caretaker" else profile.get("caretaker_id")
    return {
        "success": True,
        "uid": current_user.user_id,
        "role": role,
        "ids": {
            "user_id": current_user.user_id,
            "caretaker_id": caretaker_id,
            "selfcare_id": current_user.user_id if profile.get("selfcare_enabled") else None,
        },
        "profile": profile,
    }


@router.post("/bootstrap")
def bootstrap_profile(
    mode: Literal["user", "selfcare"] = "user",
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("auth-bootstrap", limit=20)),
):
    profile = user_repo.get_by_id(current_user.user_id) or {}
    role = str(profile.get("role") or current_user.role or "user")

    patch = {"auth_uid": current_user.user_id}
    if role == "caretaker":
        # Caretaker accounts always map caretaker_id to their own UID.
        patch["caretaker_id"] = current_user.user_id
    if mode == "selfcare":
        patch["selfcare_enabled"] = True
        if role != "caretaker":
            patch["caretaker_id"] = current_user.user_id

    updated = user_repo.upsert(current_user.user_id, patch)
    updated_role = str(updated.get("role") or role)
    caretaker_id = current_user.user_id if updated_role == "caretaker" else updated.get("caretaker_id")
    return {
        "success": True,
        "uid": current_user.user_id,
        "role": updated_role,
        "mode": mode,
        "ids": {
            "user_id": current_user.user_id,
            "caretaker_id": caretaker_id,
            "selfcare_id": current_user.user_id if updated.get("selfcare_enabled") else None,
        },
        "profile": updated,
    }
