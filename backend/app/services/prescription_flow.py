import os
import tempfile
from typing import Any, Dict, Iterable

from fastapi import HTTPException, UploadFile

from app.services.correction import correct_medicine_names
from app.services.extraction import extract_medicines
from app.services.prescription_builder import build_audio_draft, merge_draft_with_edits
from app.services.transcription import extract_medical_from_transcript, transcribe_audio


def cleanup_temp_file(path: str) -> None:
    if path and os.path.exists(path):
        os.remove(path)


async def persist_upload_to_temp(
    upload: UploadFile,
    allowed_types: Iterable[str],
    default_suffix: str,
    mime_to_ext: Dict[str, str] | None = None,
) -> tuple[str, bytes]:
    content_type = upload.content_type or "application/octet-stream"
    if content_type not in set(allowed_types):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {content_type}")

    suffix = (
        mime_to_ext.get(content_type, default_suffix) if mime_to_ext
        else os.path.splitext(upload.filename or "")[1] or default_suffix
    )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await upload.read()
        tmp.write(content)
        return tmp.name, content


def process_audio_file_to_draft(
    audio_path: str,
    language: str,
    patient_name: str,
    audio_filename: str,
) -> Dict[str, Any]:
    transcription = transcribe_audio(audio_path, language)
    if not transcription.get("success"):
        raise HTTPException(
            status_code=500,
            detail=transcription.get("error", "Transcription failed"),
        )

    transcript_text = transcription.get("text", "")
    extracted = extract_medical_from_transcript(transcript_text)
    if patient_name:
        extracted["patient_name"] = patient_name

    draft_data = build_audio_draft(
        extracted=extracted,
        transcript_text=transcript_text,
        audio_filename=audio_filename,
        language=transcription.get("language", "unknown"),
    )

    return {
        "transcription": transcription,
        "transcript_text": transcript_text,
        "extracted": extracted,
        "draft_data": draft_data,
    }


def process_text_to_draft(text: str, patient_name: str = "") -> Dict[str, Any]:
    corrected_text = correct_medicine_names(text)
    extracted = extract_medicines(corrected_text)
    if patient_name:
        extracted["patient_name"] = patient_name

    draft_data = build_audio_draft(
        extracted=extracted,
        transcript_text=text,
        audio_filename="",
        language="text",
    )
    draft_data["source"] = "manual_text"

    return {
        "corrected_text": corrected_text,
        "extracted": extracted,
        "draft_data": draft_data,
    }


def build_final_prescription_data(
    source: str,
    draft_data: Dict[str, Any],
    edits: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    final_data = merge_draft_with_edits(draft_data, edits)
    final_data["source"] = source
    final_data["status"] = "active"
    final_data["reviewed"] = True
    return final_data

