# SPEC-005: API Error Handling and Response Format

## Status
Approved

## Priority
P0

## Dependencies
- SPEC-001

## Overview
Define the standardized error response format and exception handling infrastructure for the SWET backend API. This spec covers the `AppError` exception hierarchy, the `ErrorResponse` envelope, and exception handlers for both application errors and framework errors (FastAPI `HTTPException`, Pydantic `RequestValidationError`). Every error returned by the API must conform to a single consistent format.

## Requirements

### Functional
1. Standardized error response envelope: `{ error: string, detail?: string, code?: string }`
2. `AppError` base exception class with HTTP status code, error message, optional detail, and optional error code
3. Concrete error subclasses: `NotFoundError`, `ConflictError`, `ForbiddenError`, `UnauthorizedError`, `ValidationError`, `BadRequestError`
4. Exception handler for `AppError` hierarchy returning the standardized format
5. Exception handler for FastAPI `HTTPException` converting to the standardized format
6. Exception handler for Pydantic `RequestValidationError` converting validation errors to the standardized format with field-level details
7. Catch-all handler for unhandled exceptions returning a generic 500 error (no internal details leaked)
8. All error codes should be uppercase snake_case strings (e.g., `"NOT_FOUND"`, `"CONFLICT"`, `"VALIDATION_ERROR"`)

### Non-Functional
1. Error responses must never expose stack traces, internal paths, or implementation details in production
2. Error handling adds negligible overhead (no additional DB queries or external calls)
3. All error responses include appropriate HTTP status codes
4. Error format must be JSON-serializable and consistent across all endpoints

## Technical Design

### Error Response Schema
```json
{
  "error": "Human-readable error message",
  "detail": "Optional additional context or field-level errors",
  "code": "MACHINE_READABLE_ERROR_CODE"
}
```

### Pydantic Response Model (`src/errors.py`)
```python
class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    code: str | None = None
```

### AppError Hierarchy (`src/errors.py`)
```python
class AppError(Exception):
    """Base application error."""
    status_code: int = 500
    error: str = "Internal server error"
    code: str = "INTERNAL_ERROR"
    detail: str | None = None

class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    # error set per instance, e.g., "User not found"

class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"
    # e.g., "Assessment already in progress"

class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"
    # e.g., "Account is deactivated"

class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"
    # e.g., "Invalid or missing authentication"

class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    # e.g., "Invalid input"

class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"
    # e.g., "Assessment is already completed"
```

### Exception Handlers (registered in `src/main.py`)

**AppError handler**
```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.error,
            detail=exc.detail,
            code=exc.code,
        ).model_dump(exclude_none=True),
    )
```

**HTTPException handler**
```python
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail if isinstance(exc.detail, str) else "HTTP error",
            code=f"HTTP_{exc.status_code}",
        ).model_dump(exclude_none=True),
    )
```

**RequestValidationError handler**
```python
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Convert Pydantic validation errors to a readable detail string
    # e.g., "field 'email': value is not a valid email address"
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="Validation error",
            detail=format_validation_errors(exc.errors()),
            code="VALIDATION_ERROR",
        ).model_dump(exclude_none=True),
    )
```

**Catch-all handler**
```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the full exception internally
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            code="INTERNAL_ERROR",
        ).model_dump(exclude_none=True),
    )
```

### Error Usage Examples
```python
# In service layer
async def get_assessment(db: AsyncSession, assessment_id: UUID) -> Assessment:
    assessment = await db.get(Assessment, assessment_id)
    if not assessment:
        raise NotFoundError(error="Assessment not found")
    return assessment

# In service layer - conflict
async def start_assessment(db: AsyncSession, user_id: UUID) -> Assessment:
    existing = await get_active_assessment(db, user_id)
    if existing:
        raise ConflictError(
            error="Assessment already in progress",
            detail=f"Complete or cancel assessment {existing.id} first",
        )
```

### HTTP Status Code Mapping
| Error Class | Status Code | When to Use |
|------------|-------------|-------------|
| UnauthorizedError | 401 | Missing or invalid JWT |
| ForbiddenError | 403 | Valid JWT but insufficient permissions / inactive |
| NotFoundError | 404 | Resource does not exist |
| BadRequestError | 400 | Invalid operation (e.g., submitting a completed assessment) |
| ConflictError | 409 | Resource state conflict (e.g., duplicate submission) |
| ValidationError | 422 | Input validation failure |
| AppError (base) | 500 | Unexpected application error |

## Implementation Notes
- All error classes accept `error` and `detail` as constructor arguments, with `code` and `status_code` set as class-level defaults.
- The `format_validation_errors` helper should convert Pydantic's error list into a human-readable string, joining field paths and messages.
- The catch-all handler must log the full traceback server-side before returning the sanitized 500 response.
- Service layer code raises `AppError` subclasses. Route handlers should not catch these -- they propagate to the exception handlers automatically.
- The `ErrorResponse` model is exported for use in OpenAPI response documentation via FastAPI's `responses` parameter.

## Testing Strategy
- Unit tests for: Each `AppError` subclass has correct `status_code` and `code`, `ErrorResponse` serialization with and without optional fields, `format_validation_errors` produces readable output
- Integration tests for: `AppError` raised in route returns correct JSON format, `HTTPException` raised in route returns correct JSON format, Invalid request body triggers `RequestValidationError` handler with field details, Unhandled exception returns 500 without leaking internals, All error responses conform to `ErrorResponse` schema
- E2E tests for: Frontend API client correctly parses error responses

## Acceptance Criteria
- [ ] All API error responses conform to `{ error, detail?, code? }` format
- [ ] `NotFoundError` returns 404 with `code: "NOT_FOUND"`
- [ ] `ConflictError` returns 409 with `code: "CONFLICT"`
- [ ] `ForbiddenError` returns 403 with `code: "FORBIDDEN"`
- [ ] `UnauthorizedError` returns 401 with `code: "UNAUTHORIZED"`
- [ ] `ValidationError` returns 422 with `code: "VALIDATION_ERROR"`
- [ ] `BadRequestError` returns 400 with `code: "BAD_REQUEST"`
- [ ] FastAPI `HTTPException` responses are wrapped in the standardized format
- [ ] Pydantic `RequestValidationError` responses include field-level detail strings
- [ ] Unhandled exceptions return 500 with generic message and no internal details
- [ ] All error classes are importable from `src.errors`
- [ ] Error responses are documented in OpenAPI schema via FastAPI `responses` parameter
