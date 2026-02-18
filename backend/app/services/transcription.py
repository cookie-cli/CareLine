import json
import logging

from app.services.groq_client import get_groq_client

logger = logging.getLogger(__name__)

def transcribe_audio(audio_path: str, language: str = "en") -> dict:
    """
    Transcribe audio file using Groq Whisper
    Returns: {"text": str, "language": str}
    """
    try:
        client = get_groq_client()
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3",
                response_format="text",
                language=language if language != "auto" else None
            )
        
        # Handle both dict and string responses
        if isinstance(transcription, dict):
            text = transcription.get("text", "")
        else:
            text = str(transcription)
        
        return {
            "text": text,
            "language": language if language != "auto" else "auto-detected",
            "success": True
        }
        
    except Exception:
        logger.exception("Transcription failed")
        return {
            "text": "",
            "language": "",
            "success": False,
            "error": "Transcription service unavailable"
        }

def extract_medical_from_transcript(transcript: str) -> dict:
    """
    Extract structured medical info from transcript using LLM
    """
    if not transcript or not transcript.strip():
        return {
            "patient_name": "",
            "medicines": [],
            "confidence": "low",
            "error": "Empty transcript"
        }
    
    prompt = f"""Extract medical prescription information from this transcript:

"{transcript}"

Return JSON:
{{
    "patient_name": "name or empty",
    "patient_age": "age or empty", 
    "symptoms": [],
    "medicines": [
        {{
            "name": "medicine name",
            "dosage": "",
            "frequency": "",
            "duration": "",
            "instructions": ""
        }}
    ],
    "notes": "",
    "confidence": "high/medium/low"
}}"""

    try:
        client = get_groq_client()
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": "Extract medical data from speech. Return only JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        result["raw_transcript"] = transcript
        return result
        
    except Exception:
        logger.exception("Medical extraction failed")
        return {
            "patient_name": "",
            "medicines": [],
            "confidence": "low",
            "raw_transcript": transcript,
            "error": "Medical extraction failed",
        }
