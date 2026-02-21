from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _request_id(request: Request) -> str:
    from_state = getattr(request.state, "request_id", "")
    if from_state:
        return str(from_state)
    existing = request.headers.get("X-Request-ID", "").strip()
    return existing or str(uuid4())


def _error_payload(
    *,
    request: Request,
    code: str,
    message: str,
    details: Any = None,
) -> Dict[str, Any]:
    request_id = _request_id(request)
    payload: Dict[str, Any] = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        },
    }
    if details is not None:
        payload["error"]["details"] = details
    return payload


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        details = None if isinstance(exc.detail, str) else exc.detail
        code = f"http_{exc.status_code}"
        payload = _error_payload(request=request, code=code, message=message, details=details)
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        payload = _error_payload(
            request=request,
            code="validation_error",
            message="Invalid request parameters",
            details=exc.errors(),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, _: Exception) -> JSONResponse:
        payload = _error_payload(
            request=request,
            code="internal_error",
            message="Internal server error",
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload)
