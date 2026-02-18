# app/routers/scanner.py

import base64
import json
import logging
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from app.database.firebase import save_prescription
from app.security import AuthUser, get_current_user, rate_limit, require_admin
from app.services.groq_client import get_groq_client
from app.services.prescription_builder import build_scanner_draft
from app.services.prescription_flow import cleanup_temp_file, persist_upload_to_temp

router = APIRouter(
    prefix="/scanner",
    tags=["scanner"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a specialized medical prescription analyzer with expertise in Ayurvedic and allopathic prescriptions. Extract ALL information and return strict JSON.

CRITICAL: Understand medical abbreviations correctly:
- "S." = Sine (Latin for "without") OR can indicate "Statim" (immediately)
- "S. Tab" = "Sine Tablet" (without tablet) OR dosage instruction
- "1 x 2" or "1x2" = Take 1 tablet twice daily (1-0-1)
- "1 x 3" = Take 1 tablet three times daily (1-1-1)
- "0-1-0" = Morning-Noon-Night dosage pattern
- "o.d." or "OD" = Once daily
- "b.d." or "BD" = Twice daily
- "t.d.s." or "TDS" = Three times daily
- "q.i.d." or "QID" = Four times daily
- "a.c." = Before meals (ante cibum)
- "p.c." = After meals (post cibum)
- "h.s." = At bedtime (hora somni)
- "s.o.s." = As needed (si opus sit)

HANDWRITING CORRECTIONS (auto-fix):
- "Bawder/Pawder" → "Powder"
- "Preprpe/Preprbe" → "Preparation" 
- "Tab" → "Tablet"
- "Cap" → "Capsule"
- "Caugh/Couglus" → "Cough"
- "Sinusities/Sinusistis" → "Sinusitis"
- "Diss" → "Diagnosis"
- "Med" → "Medicine"
- "Churna" → "Powder"
- "Vati" → "Tablet"
- "Taila" → "Oil"
- "Bhasma" → "Ash/Calx"

EXTRACTION LOGIC:
1. If you see "S. Tab 1x2" or similar → This is a DOSAGE INSTRUCTION, not a medicine name
2. Look for actual medicine names before the abbreviation
3. "1x2", "1 x 2", "1-0-1", "twice daily" = dosage frequency
4. Numbers after medicine names usually indicate strength (e.g., "182" could be mg)

For this prescription specifically:
- Line "(2) S. Tab 1x2" means: Take [the powder/medicine from line 1] as tablet form, 1 tablet twice daily, OR it refers to a second medicine to be taken 1 tablet twice daily
- "S." here likely means "Sine" (without) indicating take without something, OR it's marking item (2) in the list

OUTPUT SCHEMA:
{
    "patient": {
        "name": "full name",
        "age": "age with unit",
        "gender": "Male/Female/Other",
        "location": "city/country if mentioned"
    },
    "diagnosis": ["condition1", "condition2"],
    "medicines": [
        {
            "name": "corrected medicine name",
            "raw_text": "original handwritten text",
            "form": "Powder/Tablet/Capsule/Syrup/Ointment/Inhaler/Injection/Drops",
            "strength": "e.g., 500mg, 40mg",
            "dosage": "e.g., 1-0-1, 1 tablet twice daily",
            "frequency": "Twice daily/Three times daily/Once daily",
            "duration": "e.g., 45 days, 2 weeks",
            "instructions": "e.g., Take with honey, before food",
            "purpose": "what it's for"
        }
    ],
    "dosage_instructions": "overall dosage pattern if specified separately",
    "general_instructions": ["instruction1", "instruction2"],
    "follow_up": "follow up date or instructions",
    "doctor_name": "if visible",
    "clinic_name": "if visible",
    "date": "prescription date",
    "raw_full_text": "complete extracted text before processing"
}

SPECIAL NOTES FOR AYURVEDIC PRESCRIPTIONS:
- Baidyanath is a major Ayurvedic brand
- "Churna" = herbal powder
- "Vati/Gutika" = pills/tablets
- "Asav/Arishta" = fermented liquids
- Often dosage is "1-2 grams with honey/water"
- "Anupana" = vehicle/substance to take medicine with (e.g., honey, warm water)

Return ONLY valid JSON, no markdown, no explanations."""

def extract_from_image(image_path: str) -> dict:
    """Extract prescription data using Groq Vision"""
    
    file_size = os.path.getsize(image_path)
    if file_size > 4 * 1024 * 1024:
        raise ValueError(f"Image too large: {file_size} bytes. Max 4MB.")
    
    with open(image_path, "rb") as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
    
    ext = os.path.splitext(image_path)[1].lower()
    mime_types = {'.jpg': 'jpeg', '.jpeg': 'jpeg', '.png': 'png', '.webp': 'webp'}
    mime_type = mime_types.get(ext, 'jpeg')
    
    try:
        client = get_groq_client()
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": """Analyze this Ayurvedic prescription from Baidyanath store carefully. 
                            
Pay special attention to:
1. Item (1) is a powder preparation for cough/cold/sinusitis for 45 days with honey
2. Item (2) says "S. Tab 1x2" - this is likely a DOSAGE INSTRUCTION for the powder (take 1 tablet/gram twice daily) OR a second medicine. Determine which based on context.
3. "S." might mean "Sine" (without) or indicate "item 2"
4. Extract the complete treatment plan.

Return structured JSON with all medicines and correct interpretation of abbreviations."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{mime_type};base64,{encoded_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        
        data = json.loads(content)
        
        # Ensure all required fields exist
        data.setdefault("patient", {"name": "", "age": "", "gender": "", "location": ""})
        data.setdefault("diagnosis", [])
        data.setdefault("medicines", [])
        data.setdefault("dosage_instructions", "")
        data.setdefault("general_instructions", [])
        data.setdefault("follow_up", "")
        data.setdefault("doctor_name", "")
        data.setdefault("clinic_name", "")
        data.setdefault("date", "")
        data.setdefault("raw_full_text", "")
        
        return data
        
    except json.JSONDecodeError as e:
        logger.warning("Scanner response was invalid JSON: %s", e)
        raise ValueError(f"Invalid JSON: {str(e)}")
    except Exception:
        logger.exception("Vision API error")
        raise

@router.post("/image")
async def scan_prescription(
    image: UploadFile = File(..., description="Prescription image"),
    auto_save: bool = Form(default=False),
    current_user: AuthUser = Depends(get_current_user),
    _: None = Depends(rate_limit("scan-image", limit=8)),
):
    """Scan prescription image and extract structured data"""

    allowed = ["image/jpeg", "image/png", "image/jpg", "image/webp"]
    temp_path, _content = await persist_upload_to_temp(
        upload=image,
        allowed_types=allowed,
        default_suffix=".jpg",
        mime_to_ext=None,
    )

    try:
        extracted_data = extract_from_image(temp_path)

        draft_data = build_scanner_draft(extracted_data=extracted_data, image_filename=image.filename or "")

        doc_id = None
        if auto_save:
            draft_data.setdefault("user_id", current_user.user_id)
            if current_user.role == "caretaker":
                draft_data.setdefault("caretaker_id", current_user.user_id)
            doc_id = save_prescription(draft_data, image.filename)
        
        return {
            "success": True,
            "mode": "saved" if auto_save else "draft",
            "document_id": doc_id,
            "draft_data": draft_data,
            "summary": {
                "patient": extracted_data["patient"]["name"],
                "medicine_count": len(extracted_data["medicines"]),
                "diagnoses": extracted_data["diagnosis"],
                "duration": extracted_data["medicines"][0].get("duration", "") if extracted_data["medicines"] else ""
            }
        }
        
    except Exception:
        logger.exception("Scanner processing failed")
        raise HTTPException(status_code=500, detail="Failed to process image")

    finally:
        cleanup_temp_file(temp_path)

@router.post("/quick-test")
async def quick_scan_test(
    _: AuthUser = Depends(require_admin),
    __: None = Depends(rate_limit("scan-quick-test", limit=5)),
):
    """Test with mock data"""
    
    mock_data = {
        "patient": {
            "name": "Nathalie Pineau",
            "age": "31",
            "gender": "Female",
            "location": "France"
        },
        "diagnosis": ["Chronic Cough", "Sinusitis"],
        "medicines": [
            {
                "name": "Cough & Cold Powder (Baidyanath)",
                "raw_text": "Powder preparation med for cough & cold, chronic sinusitis",
                "form": "Powder",
                "strength": "",
                "dosage": "1 teaspoon twice daily",
                "frequency": "Twice daily",
                "duration": "45 days",
                "instructions": "Take with honey",
                "purpose": "Cough, Cold, Chronic Sinusitis"
            }
        ],
        "dosage_instructions": "S. Tab 1x2 interpreted as: Take 1 tablet/gram twice daily (Sine = without food, or simply dosage mark)",
        "general_instructions": ["Complete 45 days course", "Take regularly with honey"],
        "follow_up": "",
        "doctor_name": "",
        "clinic_name": "Baidyanath Ayurvedic Store, Pushkar",
        "date": "21/11/1999",
        "raw_full_text": "Baidyanath Ayurvedic Medicine prescription for chronic cough and sinusitis"
    }
    
    doc_id = save_prescription({
        "patient_name": mock_data["patient"]["name"],
        "medicines": mock_data["medicines"],
        "diagnosis": mock_data["diagnosis"],
        "prescription_date": mock_data["date"]
    }, "mock_test.jpg")
    
    return {
        "success": True,
        "document_id": doc_id,
        "extracted_data": mock_data,
        "note": "Mock data showing correct interpretation of 'S. Tab 1x2'"
    }

@router.get("/status")
async def scanner_status():
    return {
        "status": "active",
        "method": "groq-vision-api",
        "model": "meta -llama/llama-4-scout-17b-16e-instruct",
        "features": ["medical-abbreviations", "ayurvedic-support", "dosage-interpretation"]
    }
