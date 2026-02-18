# app/main.py

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os
import logging

from app.config import settings

app = FastAPI(title="Medical Prescription API")
logger = logging.getLogger(__name__)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    if request.url.path in {"/static/auth-test.html", "/static/record.html"} and not settings.ENABLE_TEST_TOOLS:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    response = await call_next(request)
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

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    logger.info("Static files mounted at %s", static_dir)
else:
    logger.warning("Static directory not found at %s", static_dir)

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

@app.get("/")
async def root():
    endpoints = {
        "scanner": "/api/v1/scanner",
        "audio": "/api/v1/audio",
        "nudges": "/api/v1/nudges",
        "status": "/api/v1/status",
        "prescriptions": "/api/v1/prescriptions",
        "linking": "/api/v1/linking",
        "recorder": "/static/record.html",
    }
    if settings.ENABLE_TEST_TOOLS:
        endpoints["auth_tester"] = "/static/auth-test.html"
    return {
        "message": "Medical Prescription API",
        "endpoints": endpoints,
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
