# app/routers/prescriptions.py

from fastapi import APIRouter, UploadFile, File, Query, Body, Form, HTTPException
from app.database.firebase import save_prescription, get_prescriptions, get_prescription_by_id
from typing import Any, Dict
from app.services.prescription_flow import (
    build_final_prescription_data,
    cleanup_temp_file,
    persist_upload_to_temp,
    process_audio_file_to_draft,
    process_text_to_draft,
)
from app.services.nudges_engine import ensure_daily_nudges_for_prescription, today_str
from app.services.family_linking import get_users_for_caretaker

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])

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
):
    """
    Save final user-reviewed prescription data.
    Frontend flow: scan/upload -> edit draft -> call finalize.
    """
    try:
        final_data = build_final_prescription_data(source, draft_data, edits)

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-text")
async def process_text(
    text: str = Query(..., description="Prescription text to process"),
    patient_name: str = Query("Amma", description="Patient name"),
    auto_save: bool = Query(False, description="Directly save without frontend review"),
):
    """
    Process raw text and return draft for frontend review.
    """
    try:
        pipeline = process_text_to_draft(text=text, patient_name=patient_name)
        draft_data = pipeline["draft_data"]

        doc_id = None
        if auto_save:
            doc_id = save_prescription(draft_data)

        return {
            "success": True,
            "mode": "saved" if auto_save else "draft",
            "document_id": doc_id,
            "corrected": pipeline["corrected_text"],
            "draft_data": draft_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
async def list_prescriptions(patient_name: str = Query(None, description="Filter by patient name")):
    """
    List all prescriptions, optionally filter by patient name
    """
    try:
        results = get_prescriptions(patient_name)
        return {
            "success": True,
            "count": len(results),
            "prescriptions": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{doc_id}")
async def get_prescription(doc_id: str):
    """
    Get single prescription by ID
    """
    result = get_prescription_by_id(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Prescription not found")
    
    return {
        "success": True,
        "prescription": result
    }
