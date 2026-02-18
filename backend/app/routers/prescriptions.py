# app/routers/prescriptions.py

import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile

from app.database.firebase import save_prescription
from app.repositories import prescription_repo
from app.security import (
    AuthUser,
    can_access_prescription,
    can_access_user,
    ensure_caretaker_access,
    get_current_user,
    rate_limit,
)
from app.services.prescription_flow import (
    build_final_prescription_data,
    cleanup_temp_file,
    persist_upload_to_temp,
    process_audio_file_to_draft,
    process_text_to_draft,
)
from app.services.nudges_engine import ensure_daily_nudges_for_prescription, today_str
from app.services.family_linking import get_users_for_caretaker

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/prescriptions",
    tags=["prescriptions"],
    dependencies=[Depends(get_current_user)],
)

ALLOWED_AUDIO_TYPES = [
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/webm", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/flac",
]

MIME_TO_EXT = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/webm": ".webm", "audio/ogg": ".ogg",
    "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/flac": ".flac",
}


@router.post("/process-audio")
async def process_audio(
    audio: UploadFile = File(..., description="Audio file (WAV, MP3, etc.)"),
    language: str = Form(default="auto"),
    patient_name: str = Form(default=""),
    auto_save: bool = Form(default=False),
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("prescriptions-process-audio", limit=10)),
):
    """
    Upload audio and return draft data for frontend editing.
    Set auto_save=true only for direct-save mode.
    """
    temp_path, _ = await persist_upload_to_temp(
        upload=audio,
        allowed_types=ALLOWED_AUDIO_TYPES,
        default_suffix=".wav",
        mime_to_ext=MIME_TO_EXT,
    )

    try:
        pipeline = process_audio_file_to_draft(
            audio_path=temp_path,
            language=language,
            patient_name=patient_name,
            audio_filename=audio.filename or "",
        )

        draft_data = pipeline["draft_data"]
        transcription = pipeline["transcription"]

        doc_id = None
        if auto_save:
            draft_data.setdefault("user_id", current_user.user_id)
            if current_user.role == "caretaker":
                draft_data.setdefault("caretaker_id", current_user.user_id)
            doc_id = save_prescription(draft_data, audio.filename)

        return {
            "success": True,
            "mode": "saved" if auto_save else "draft",
            "document_id": doc_id,
            "transcription": {
                "text": pipeline["transcript_text"],
                "language": transcription.get("language"),
            },
            "draft_data": draft_data,
        }
    finally:
        cleanup_temp_file(temp_path)


@router.post("/finalize")
async def finalize_prescription(
    source: str = Body(..., description="audio | scanner | manual"),
    draft_data: Dict[str, Any] = Body(..., description="Draft payload from scanner/audio endpoint"),
    edits: Dict[str, Any] | None = Body(default=None, description="Only changed fields from frontend"),
    file_name: str = Body(default="", description="Original file name if any"),
    create_nudges: bool = Body(default=True, description="Create daily reminder nudges if caretaker_id exists"),
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("prescriptions-finalize", limit=20)),
):
    """
    Save final user-reviewed prescription data.
    Frontend flow: scan/upload -> edit draft -> call finalize.
    """
    try:
        final_data = build_final_prescription_data(source, draft_data, edits)

        # Enforce ownership by auth role.
        if current_user.role == "user":
            final_data["user_id"] = current_user.user_id
            caretaker_id = final_data.get("caretaker_id")
            if caretaker_id:
                ensure_caretaker_access(current_user, caretaker_id)
        elif current_user.role == "caretaker":
            final_data.setdefault("caretaker_id", current_user.user_id)
            ensure_caretaker_access(current_user, final_data["caretaker_id"])
            if final_data.get("user_id") and not can_access_user(current_user, final_data["user_id"]):
                raise HTTPException(status_code=403, detail="Forbidden")

        # Auto-attach user if caretaker is linked and user_id is missing.
        if final_data.get("caretaker_id") and not final_data.get("user_id"):
            linked_users = get_users_for_caretaker(final_data["caretaker_id"])
            if linked_users:
                final_data["user_id"] = linked_users[0]

        # Self-care mode: user receives reminders directly from app.
        if final_data.get("user_id") and not final_data.get("caretaker_id"):
            final_data["caretaker_id"] = final_data["user_id"]

        doc_id = save_prescription(final_data, file_name or None)

        nudge_sync = None
        if create_nudges:
            nudge_sync = ensure_daily_nudges_for_prescription(
                prescription_data=final_data,
                prescription_id=doc_id,
                for_date=today_str(),
            )

        return {
            "success": True,
            "document_id": doc_id,
            "final_data": final_data,
            "nudge_sync": nudge_sync,
        }
    except Exception:
        logger.exception("Failed to finalize prescription")
        raise HTTPException(status_code=500, detail="Failed to finalize prescription")

@router.post("/process-text")
async def process_text(
    text: str = Query(..., description="Prescription text to process"),
    patient_name: str = Query("Amma", description="Patient name"),
    auto_save: bool = Query(False, description="Directly save without frontend review"),
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("prescriptions-process-text", limit=20)),
):
    """
    Process raw text and return draft for frontend review.
    """
    try:
        pipeline = process_text_to_draft(text=text, patient_name=patient_name)
        draft_data = pipeline["draft_data"]

        doc_id = None
        if auto_save:
            draft_data.setdefault("user_id", current_user.user_id)
            if current_user.role == "caretaker":
                draft_data.setdefault("caretaker_id", current_user.user_id)
            doc_id = save_prescription(draft_data)

        return {
            "success": True,
            "mode": "saved" if auto_save else "draft",
            "document_id": doc_id,
            "corrected": pipeline["corrected_text"],
            "draft_data": draft_data,
        }
    except Exception:
        logger.exception("Failed to process text prescription")
        raise HTTPException(status_code=500, detail="Failed to process text")

@router.get("/")
async def list_prescriptions(
    patient_name: str = Query(None, description="Filter by patient name"),
    current_user: AuthUser = Depends(get_current_user),
):
    """
    List all prescriptions, optionally filter by patient name
    """
    try:
        if current_user.role == "admin":
            results = prescription_repo.list_for_admin(patient_name)
        elif current_user.role == "caretaker":
            results = prescription_repo.list_for_caretaker(current_user.user_id, patient_name)
        else:
            results = prescription_repo.list_for_user(current_user.user_id, patient_name)
        return {
            "success": True,
            "count": len(results),
            "prescriptions": results
        }
    except Exception:
        logger.exception("Failed to list prescriptions")
        raise HTTPException(status_code=500, detail="Failed to list prescriptions")

@router.get("/{doc_id}")
async def get_prescription(
    doc_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """
    Get single prescription by ID
    """
    result = prescription_repo.get_by_id(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if not can_access_prescription(current_user, result):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    return {
        "success": True,
        "prescription": result
    }
