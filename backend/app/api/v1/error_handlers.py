"""Map domain exceptions to HTTP responses with consistent shape."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import TahrixError
from app.core.logging import get_logger

logger = get_logger(__name__)


def _payload(code: str, message: str, details: dict | None = None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TahrixError)
    async def _handle_tahrix(_: Request, exc: TahrixError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("error.domain", code=exc.code, message=exc.message,
                         details=exc.details)
        else:
            logger.info("error.domain", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.details or None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic v2 errors() may include bytes (raw input). Sanitize for JSON.
        clean_errors = []
        for err in exc.errors():
            safe = {}
            for k, v in err.items():
                if isinstance(v, bytes):
                    safe[k] = v.decode("utf-8", errors="replace")
                elif isinstance(v, (list, tuple)):
                    safe[k] = [
                        x.decode("utf-8", errors="replace") if isinstance(x, bytes) else x
                        for x in v
                    ]
                else:
                    safe[k] = v
            clean_errors.append(safe)
        return JSONResponse(
            status_code=422,
            content=_payload("validation_error", "Request validation failed",
                             {"errors": clean_errors}),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("error.unexpected", error=str(exc))
        return JSONResponse(
            status_code=500,
            content=_payload("internal_error", "Unexpected server error"),
        )
