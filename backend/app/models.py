# app/models.py

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class Medicine(BaseModel):
    name: str
    dosage: str = ""
    timing: str = ""
    frequency: str = ""

class PrescriptionInput(BaseModel):
    medicines: List[Medicine]
    patient_name: str
    notes: Optional[str] = ""

class Prescription(PrescriptionInput):
    created_at: datetime = datetime.now()
    status: str = "active"

class PrescriptionResponse(Prescription):
    id: str
    audio_file: Optional[str] = None

class AudioResponse(BaseModel):
    success: bool
    document_id: str
    raw: str
    corrected: str
    data: PrescriptionInput

class NudgeRequest(BaseModel):
    patient_id: str
    message: str = "Did you take your medicines today?"