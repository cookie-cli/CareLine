# app/routers/prescriptions.py

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Form
from fastapi.responses import JSONResponse
from app.services.transcription import transcribe_audio
from app.services.correction import correct_medicine_names
from app.services.extraction import extract_medicines
from app.database.firebase import save_prescription, get_prescriptions, get_prescription_by_id
from app.models import AudioResponse, PrescriptionInput
import os
import tempfile

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])

@router.post("/process-audio", response_model=AudioResponse)
async def process_audio(
    audio: UploadFile = File(..., description="Audio file (WAV, MP3, etc.)")
):
    """
    Full pipeline: Upload audio → transcribe → correct → extract → save to Firebase
    """
    # Validate file type
    allowed_types = ["audio/wav", "audio/mpeg", "audio/mp3", "audio/webm", "audio/ogg"]
    if audio.content_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type: {audio.content_type}. Allowed: {allowed_types}"
        )
    
    # Create temp file
    suffix = os.path.splitext(audio.filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        temp_path = tmp.name
    
    try:
        print(f"Processing: {temp_path} ({len(content)} bytes)")
        
        # Step 1: Transcribe
        print("Step 1: Transcribing...")
        raw_text = transcribe_audio(temp_path)
        print(f"Raw: {raw_text}")
        
        # Step 2: Correct medicine names
        print("Step 2: Correcting...")
        corrected_text = correct_medicine_names(raw_text)
        print(f"Corrected: {corrected_text}")
        
        # Step 3: Extract structured data
        print("Step 3: Extracting...")
        structured = extract_medicines(corrected_text)
        print(f"Structured: {structured}")
        
        # Step 4: Save to Firebase
        print("Step 4: Saving...")
        doc_id = save_prescription(structured, audio.filename)
        print(f"Saved: {doc_id}")
        
        return AudioResponse(
            success=True,
            document_id=doc_id,
            raw=raw_text,
            corrected=corrected_text,
            data=PrescriptionInput(**structured)
        )
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

@router.post("/process-text")
async def process_text(
    text: str = Query(..., description="Prescription text to process"),
    patient_name: str = Query("Amma", description="Patient name")
):
    """
    Process text directly (for testing without audio)
    """
    try:
        # Skip transcription, just correct and extract
        corrected_text = correct_medicine_names(text)
        structured = extract_medicines(corrected_text)
        structured["patient_name"] = patient_name
        
        doc_id = save_prescription(structured)
        
        return {
            "success": True,
            "document_id": doc_id,
            "corrected": corrected_text,
            "data": structured
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