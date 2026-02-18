# app/routers/audio.py

from fastapi import APIRouter, Depends, File, Form, UploadFile
from app.database.firebase import save_prescription
from app.services.prescription_flow import (
    cleanup_temp_file,
    persist_upload_to_temp,
    process_audio_file_to_draft,
)
from app.security import AuthUser, get_current_user, rate_limit

router = APIRouter(
    prefix="/audio",
    tags=["audio"],
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

@router.post("/upload")
async def upload_audio(
    audio: UploadFile = File(...),
    language: str = Form(default="auto"),
    patient_name: str = Form(default=""),
    auto_save: bool = Form(default=False),
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("audio-upload", limit=10)),
):
    """Upload audio → Transcribe → Extract → Return editable draft (or save if auto_save=true)."""

    audio_path, _ = await persist_upload_to_temp(
        upload=audio,
        allowed_types=ALLOWED_AUDIO_TYPES,
        default_suffix=".wav",
        mime_to_ext=MIME_TO_EXT,
    )

    try:
        pipeline = process_audio_file_to_draft(
            audio_path=audio_path,
            language=language,
            patient_name=patient_name,
            audio_filename=audio.filename or "",
        )

        draft_data = pipeline["draft_data"]
        transcription = pipeline["transcription"]
        transcript_text = pipeline["transcript_text"]

        doc_id = None
        if auto_save:
            payload = {**draft_data, "type": "audio_transcription"}
            payload.setdefault("user_id", current_user.user_id)
            if current_user.role == "caretaker":
                payload.setdefault("caretaker_id", current_user.user_id)
            doc_id = save_prescription(payload, audio.filename)

        return {
            "success": True,
            "mode": "saved" if auto_save else "draft",
            "document_id": doc_id,
            "transcription": {
                "text": transcript_text,
                "language": transcription.get("language")
            },
            "draft_data": draft_data
        }

    finally:
        cleanup_temp_file(audio_path)

@router.post("/record")
async def process_recorded_audio(
    audio: UploadFile = File(...),
    patient_name: str = Form(default=""),
    auto_save: bool = Form(default=False),
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("audio-record", limit=10)),
):
    """Browser recording endpoint"""
    return await upload_audio(
        audio=audio,
        language="auto",
        patient_name=patient_name,
        auto_save=auto_save,
        current_user=current_user,
    )

@router.get("/status")
async def audio_status():
    return {"status": "active", "service": "transcription"}
