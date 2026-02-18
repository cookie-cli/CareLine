# app/config.py

import os
import hashlib
from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class Settings:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "firebase-key.json")
    AUTH_REQUIRED = _get_bool("AUTH_REQUIRED", True)
    AUTH_DEBUG = _get_bool("AUTH_DEBUG", False)
    FIREBASE_CHECK_REVOKED = _get_bool("FIREBASE_CHECK_REVOKED", False)
    ENABLE_TEST_TOOLS = _get_bool("ENABLE_TEST_TOOLS", False)
    LINK_CODE_LENGTH = _get_int("LINK_CODE_LENGTH", 8)
    LINK_CODE_MAX_ATTEMPTS = _get_int("LINK_CODE_MAX_ATTEMPTS", 8)
    LINK_QR_BASE_URL = os.getenv("LINK_QR_BASE_URL", "https://careline.app/link")
    LINK_CODE_PEPPER = os.getenv("LINK_CODE_PEPPER", "")
    ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
        if origin.strip()
    ]
    MAX_UPLOAD_SIZE_MB = _get_int("MAX_UPLOAD_SIZE_MB", 10)
    RATE_LIMIT_PER_MINUTE = _get_int("RATE_LIMIT_PER_MINUTE", 30)
    
    @classmethod
    def validate(cls):
        if not cls.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY not found in .env")

settings = Settings()


def link_code_hash(normalized_code: str) -> str:
    digest_input = f"{settings.LINK_CODE_PEPPER}:{normalized_code}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()
