# app/database/firebase.py

import logging
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from app.config import settings

logger = logging.getLogger(__name__)


def _resolve_key_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    backend_root = Path(__file__).resolve().parents[2]
    project_root = backend_root.parent
    search_paths = [
        Path.cwd() / candidate,
        backend_root / candidate,
        project_root / candidate,
    ]
    for path in search_paths:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Firebase key file not found at '{raw_path}'. "
        "Set FIREBASE_KEY_PATH to a valid local service-account JSON path."
    )


# Initialize Firebase
if not firebase_admin._apps:
    key_path = _resolve_key_path(settings.FIREBASE_KEY_PATH)
    cred = credentials.Certificate(str(key_path))
    firebase_admin.initialize_app(cred)
    logger.info("Firebase connected")

db = firestore.client()

def save_prescription(data: dict, audio_file: str = None) -> str:
    """Save to Firestore"""
    doc_ref = db.collection("prescriptions").add({
        **data,
        "created_at": datetime.now().isoformat(),
        "audio_file": audio_file,
        "status": "active"
    })
    return doc_ref[1].id
