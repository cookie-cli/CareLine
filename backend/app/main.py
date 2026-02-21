# app/main.py
from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

from app.api_errors import register_error_handlers
from app.config import settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Medical Prescription API",
    version=settings.API_VERSION,
)
logger = logging.getLogger(__name__)
register_error_handlers(app)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "").strip() or os.urandom(8).hex()
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self)"
    response.headers["Cache-Control"] = "no-store"
    return response

# CORS for browser recording
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials="*" not in settings.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers with error handling
try:
    from app.routers import scanner
    app.include_router(scanner.router, prefix="/api/v1")
except Exception as e:
    logger.exception("Error loading scanner router: %s", e)

try:
    from app.routers import audio
    app.include_router(audio.router, prefix="/api/v1")
except Exception as e:
    logger.exception("Error loading audio router: %s", e)

try:
    from app.routers import nudges
    app.include_router(nudges.router, prefix="/api/v1")
except Exception as e:
    logger.exception("Error loading nudges router: %s", e)

try:
    from app.routers import status
    app.include_router(status.router, prefix="/api/v1")
except Exception as e:
    logger.exception("Error loading status router: %s", e)

try:
    from app.routers import prescriptions
    app.include_router(prescriptions.router, prefix="/api/v1")
except Exception as e:
    logger.exception("Error loading prescriptions router: %s", e)

try:
    from app.routers import linking
    app.include_router(linking.router, prefix="/api/v1")
except Exception as e:
    logger.exception("Error loading linking router: %s", e)

try:
    from app.routers import auth
    app.include_router(auth.router, prefix="/api/v1")
except Exception as e:
    logger.exception("Error loading auth router: %s", e)

@app.get("/")
async def root():
    endpoints = {
        "scanner": "/api/v1/scanner",
        "audio": "/api/v1/audio",
        "nudges": "/api/v1/nudges",
        "status": "/api/v1/status",
        "prescriptions": "/api/v1/prescriptions",
        "linking": "/api/v1/linking",
        "auth": "/api/v1/auth",
    }
    return {
        "message": "Medical Prescription API",
        "endpoints": endpoints,
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
