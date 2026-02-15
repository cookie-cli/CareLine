# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import sys

app = FastAPI(title="Medical Prescription API")

# CORS for browser recording
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    print(f"✅ Static files mounted at {static_dir}")
else:
    print(f"⚠️ Warning: Static directory not found at {static_dir}")

# Import and include routers with error handling
try:
    from app.routers import scanner
    app.include_router(scanner.router, prefix="/api/v1")
    print("✅ Scanner router loaded")
except Exception as e:
    print(f"❌ Error loading scanner router: {e}")

try:
    from app.routers import audio
    app.include_router(audio.router, prefix="/api/v1")
    print("✅ Audio router loaded")
except Exception as e:
    print(f"❌ Error loading audio router: {e}")

try:
    from app.routers import nudges
    app.include_router(nudges.router, prefix="/api/v1")
    print("✅ Nudges router loaded")
except Exception as e:
    print(f"❌ Error loading nudges router: {e}")

try:
    from app.routers import status
    app.include_router(status.router, prefix="/api/v1")
    print("✅ Status router loaded")
except Exception as e:
    print(f"❌ Error loading status router: {e}")

try:
    from app.routers import prescriptions
    app.include_router(prescriptions.router, prefix="/api/v1")
    print("✅ Prescriptions router loaded")
except Exception as e:
    print(f"❌ Error loading prescriptions router: {e}")

try:
    from app.routers import linking
    app.include_router(linking.router, prefix="/api/v1")
    print("✅ Linking router loaded")
except Exception as e:
    print(f"❌ Error loading linking router: {e}")

@app.get("/")
async def root():
    return {
        "message": "Medical Prescription API",
        "endpoints": {
            "scanner": "/api/v1/scanner",
            "audio": "/api/v1/audio",
            "nudges": "/api/v1/nudges",
            "status": "/api/v1/status",
            "prescriptions": "/api/v1/prescriptions",
            "linking": "/api/v1/linking",
            "recorder": "/static/record.html"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
