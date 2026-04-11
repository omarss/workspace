"""Standardized error handling and response format."""

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: str
    detail: str | None = None
    code: str | None = None


class AppError(Exception):
    """Base application error with structured error info."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str | None = None,
        detail: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.detail = detail
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: Any = None):
        detail = f"{resource} not found"
        if identifier:
            detail = f"{resource} with id '{identifier}' not found"
        super().__init__(message=detail, status_code=404, code="not_found")


class ConflictError(AppError):
    def __init__(self, message: str):
        super().__init__(message=message, status_code=409, code="conflict")


class ForbiddenError(AppError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(message=message, status_code=403, code="forbidden")


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message=message, status_code=401, code="unauthorized")


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=exc.message,
                detail=exc.detail,
                code=exc.code,
            ).model_dump(exclude_none=True),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=str(exc.detail),
                code="http_error",
            ).model_dump(exclude_none=True),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        first_error = errors[0] if errors else {}
        field = " -> ".join(str(loc) for loc in first_error.get("loc", []))
        message = first_error.get("msg", "Validation error")

        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error=f"Validation error: {field}: {message}",
                detail=str(errors),
                code="validation_error",
            ).model_dump(exclude_none=True),
        )
