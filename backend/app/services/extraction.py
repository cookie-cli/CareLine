# app/services/extraction.py

import json
from groq import Groq
from app.config import settings

client = Groq(api_key=settings.GROQ_API_KEY)

SYSTEM_PROMPT = """You are a medical prescription parser. Extract medicine information from the text and return ONLY valid JSON.

Return this exact structure:
{
  "medicines": [
    {
      "name": "medicine name",
      "dosage": "e.g., 40mg, 500mg",
      "timing": "morning/afternoon/night/before food/after food/bedtime",
      "frequency": "once/twice/thrice daily"
    }
  ],
  "patient_name": "name if mentioned, else empty string",
  "notes": "any other instructions or empty string"
}

Rules:
- Extract exact medicine names
- Dosage should include number and unit (mg, ml, g)
- Timing: infer from "morning", "night", "before breakfast", "after lunch", etc.
- Frequency: "once daily" for 1 time, "twice daily" for 2 times
- Patient name: look for "Amma", "Papa", "Mummy", or actual names
- If information is missing, use empty string"""

def extract_medicines(text: str) -> dict:
    """
    Extract structured medicine data using Groq LLM
    """
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ],
        response_format={"type": "json_object"},
        temperature=0.1  # Low temperature for consistent output
    )
    
    result = json.loads(response.choices[0].message.content)
    
    # Ensure all required fields exist
    if "medicines" not in result:
        result["medicines"] = []
    if "patient_name" not in result:
        result["patient_name"] = ""
    if "notes" not in result:
        result["notes"] = ""
        
    return result