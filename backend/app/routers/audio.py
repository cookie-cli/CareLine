# app/routers/audio.py

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from app.database.firebase import save_prescription
from app.services.transcription import transcribe_audio, extract_medical_from_transcript  # Use service
import tempfile
import os

router = APIRouter(prefix="/audio", tags=["audio"])

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
    save_to_firebase: bool = Form(default=True)
):
    """Upload audio → Transcribe → Extract medical info → Save"""
    
    content_type = audio.content_type or "application/octet-stream"
    
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {content_type}")
    
    ext = MIME_TO_EXT.get(content_type, ".wav")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await audio.read()
        tmp.write(content)
        audio_path = tmp.name
    
    try:
        # Step 1: Transcribe using service
        transcription = transcribe_audio(audio_path, language)
        
        if not transcription["success"]:
            raise HTTPException(status_code=500, detail=transcription.get("error", "Transcription failed"))
        
        transcript_text = transcription["text"]
        
        # Step 2: Extract medical info using service
        extracted = extract_medical_from_transcript(transcript_text)
        
        if patient_name:
            extracted["patient_name"] = patient_name
        
        # Step 3: Save to Firebase
        doc_id = None
        if save_to_firebase:
            storage_data = {
                "type": "audio_transcription",
                "patient_name": extracted.get("patient_name", ""),
                "patient_age": extracted.get("patient_age", ""),
                "symptoms": extracted.get("symptoms", []),
                "medicines": extracted.get("medicines", []),
                "raw_transcript": transcript_text,
                "extracted_data": extracted,
                "audio_filename": audio.filename,
                "language": transcription.get("language", "unknown"),
                "confidence": extracted.get("confidence", "medium")
            }
            doc_id = save_prescription(storage_data, audio.filename)
        
        return {
            "success": True,
            "document_id": doc_id,
            "transcription": {
                "text": transcript_text,
                "language": transcription.get("language")
            },
            "extracted": extracted
        }
        
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

@router.post("/record")
async def process_recorded_audio(
    audio: UploadFile = File(...),
    patient_name: str = Form(default="")
):
    """Browser recording endpoint"""
    return await upload_audio(audio=audio, language="auto", patient_name=patient_name)

@router.get("/status")
async def audio_status():
    return {"status": "active", "service": "transcription"}