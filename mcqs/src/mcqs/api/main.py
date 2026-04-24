"""FastAPI app factory + uvicorn entry.

Exposed routes live under `/v1/mcq/...`. `/v1/mcq/health` is public; every
other endpoint requires `X-Api-Key`. The OpenAPI surface description is
served at `/v1/mcq/api-docs` (Swagger UI), `/v1/mcq/redoc`, and
`/v1/mcq/openapi.json` — the `api-docs` name leaves `/v1/mcq/docs/*` free
for the source-docs browsing endpoints consumed by omono.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import settings
from .routes import router
from .usage import ApiUsageMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="mcqs API",
        version="0.1.0",
        description=(
            "Multiple-choice question bank generated from vrtx-ai/docs-bundle. "
            "Every data endpoint requires `X-Api-Key`. "
            "Three question types: knowledge / analytical / problem_solving. "
            "Questions can be tagged with multiple topics within a subject."
        ),
        docs_url="/v1/mcq/api-docs",
        redoc_url="/v1/mcq/redoc",
        openapi_url="/v1/mcq/openapi.json",
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Flatten pydantic's structured errors into a single-string shape
        # consistent with gplaces so clients have one handler to write.
        first = exc.errors()[0] if exc.errors() else {"msg": "invalid request"}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "query")
        msg = first.get("msg", "invalid request")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"{loc}: {msg}" if loc else msg},
        )

    app.add_middleware(ApiUsageMiddleware)
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    if not settings.mcqs_api_key:
        raise SystemExit(
            "MCQS_API_KEY is empty — set it in .env before starting the API."
        )
    uvicorn.run(
        "mcqs.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
