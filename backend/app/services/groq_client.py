from __future__ import annotations

from functools import lru_cache

from groq import Groq

from app.config import settings


@lru_cache(maxsize=1)
def get_groq_client() -> Groq:
    api_key = (settings.GROQ_API_KEY or "").strip()
    if not api_key or api_key.startswith("your_"):
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=api_key)
