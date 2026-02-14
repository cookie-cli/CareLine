# app/services/transcription.py

from groq import Groq
from app.config import settings
import json

client = Groq(api_key=settings.GROQ_API_KEY)

def transcribe_audio(audio_path: str, language: str = "en") -> dict:
    """
    Transcribe audio file using Groq Whisper
    Returns: {"text": str, "language": str}
    """
    try:
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
        
    except Exception as e:
        print(f"Transcription error: {e}")
        return {
            "text": "",
            "language": "",
            "success": False,
            "error": str(e)
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
        
    except Exception as e:
        print(f"Extraction error: {e}")
        return {
            "patient_name": "",
            "medicines": [],
            "confidence": "low",
            "raw_transcript": transcript,
            "error": str(e)
        }