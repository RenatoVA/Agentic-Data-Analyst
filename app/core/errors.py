from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    status_code = 400
    code = "APP_ERROR"

    def __init__(self, detail: str, *, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class ConfigNotFoundError(AppError):
    status_code = 404
    code = "CONFIG_NOT_FOUND"


class ConfigValidationError(AppError):
    status_code = 422
    code = "CONFIG_INVALID"


class ToolResolutionError(AppError):
    status_code = 422
    code = "TOOL_NOT_REGISTERED"


class STTTranscriptionError(AppError):
    status_code = 502
    code = "STT_TRANSCRIPTION_FAILED"


class UserNotRegisteredError(AppError):
    status_code = 404
    code = "USER_NOT_REGISTERED"


class UserRegistrationError(AppError):
    status_code = 500
    code = "USER_REGISTRATION_FAILED"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning("AppError [%s]: %s", exc.code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_SERVER_ERROR", "detail": "Unexpected server error."},
        )
