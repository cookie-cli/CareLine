# app/database/firebase.py

import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from app.config import settings

# Initialize Firebase
if not firebase_admin._apps:
    if not os.path.exists(settings.FIREBASE_KEY_PATH):
        raise FileNotFoundError(f"Firebase key not found: {settings.FIREBASE_KEY_PATH}")
    
    cred = credentials.Certificate(settings.FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)
    print("✅ Firebase connected")

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

def get_prescriptions(patient_name: str = None):
    """Get from Firestore"""
    query = db.collection("prescriptions")
    
    if patient_name:
        query = query.where("patient_name", "==", patient_name)
    
    docs = query.order_by("created_at", descending=True).stream()
    
    results = []
    for doc in docs:
        doc_dict = doc.to_dict()
        doc_dict["id"] = doc.id
        results.append(doc_dict)
    
    return results

def get_prescription_by_id(doc_id: str):
    """Get single prescription"""
    doc = db.collection("prescriptions").document(doc_id).get()
    if not doc.exists:
        return None
    
    result = doc.to_dict()
    result["id"] = doc.id
    return result

def update_prescription_status(doc_id: str, status: str):
    """Update status"""
    db.collection("prescriptions").document(doc_id).update({
        "status": status,
        "updated_at": datetime.now().isoformat()
    })
    return True