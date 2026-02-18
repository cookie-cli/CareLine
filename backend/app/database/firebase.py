# app/database/firebase.py

import os
import logging
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from app.config import settings

logger = logging.getLogger(__name__)

# Initialize Firebase
if not firebase_admin._apps:
    if not os.path.exists(settings.FIREBASE_KEY_PATH):
        raise FileNotFoundError(f"Firebase key not found: {settings.FIREBASE_KEY_PATH}")
    
    cred = credentials.Certificate(settings.FIREBASE_KEY_PATH)
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
