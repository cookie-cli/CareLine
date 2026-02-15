from typing import Any, Dict


def build_audio_draft(
    extracted: Dict[str, Any],
    transcript_text: str,
    audio_filename: str,
    language: str,
) -> Dict[str, Any]:
    """Normalize audio extraction output into an editable draft payload."""
    return {
        "source": "audio",
        "patient_name": extracted.get("patient_name", ""),
        "patient_age": extracted.get("patient_age", ""),
        "patient_gender": extracted.get("patient_gender", ""),
        "patient_location": extracted.get("patient_location", ""),
        "diagnosis": extracted.get("diagnosis", []),
        "symptoms": extracted.get("symptoms", []),
        "medicines": extracted.get("medicines", []),
        "dosage_instructions": extracted.get("dosage_instructions", ""),
        "general_instructions": extracted.get("general_instructions", []),
        "follow_up": extracted.get("follow_up", ""),
        "doctor_name": extracted.get("doctor_name", ""),
        "clinic_name": extracted.get("clinic_name", ""),
        "prescription_date": extracted.get("prescription_date", ""),
        "notes": extracted.get("notes", ""),
        "confidence": extracted.get("confidence", "medium"),
        "raw_text": transcript_text,
        "audio_filename": audio_filename,
        "language": language,
        "extracted_data": extracted,
    }


def build_scanner_draft(extracted_data: Dict[str, Any], image_filename: str) -> Dict[str, Any]:
    """Normalize scanner extraction output into an editable draft payload."""
    patient = extracted_data.get("patient", {}) or {}

    return {
        "source": "scanner",
        "patient_name": patient.get("name", ""),
        "patient_age": patient.get("age", ""),
        "patient_gender": patient.get("gender", ""),
        "patient_location": patient.get("location", ""),
        "diagnosis": extracted_data.get("diagnosis", []),
        "symptoms": extracted_data.get("symptoms", []),
        "medicines": extracted_data.get("medicines", []),
        "dosage_instructions": extracted_data.get("dosage_instructions", ""),
        "general_instructions": extracted_data.get("general_instructions", []),
        "follow_up": extracted_data.get("follow_up", ""),
        "doctor_name": extracted_data.get("doctor_name", ""),
        "clinic_name": extracted_data.get("clinic_name", ""),
        "prescription_date": extracted_data.get("date", ""),
        "notes": extracted_data.get("notes", ""),
        "raw_text": extracted_data.get("raw_full_text", ""),
        "image_filename": image_filename,
        "extracted_data": extracted_data,
    }


def merge_draft_with_edits(draft: Dict[str, Any], edits: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Apply shallow edits over draft for frontend confirmation flow.
    Frontend can send only fields user changed.
    """
    final_data = dict(draft or {})
    if edits:
        final_data.update(edits)
    return final_data

