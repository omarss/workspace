"""FastAPI app factory + uvicorn entry.

Exposes one endpoint, `GET /v1/places`, per the contract in
`FEEDBACK.md` at the repo root. The app is read-only against Postgres —
it never writes, which is why no DB migration story is wired into it.
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
    # Auto-docs live under /v1/ so the existing nginx `location /v1/…`
    # block reverse-proxies them without a new rule. They describe the
    # surface only — every data endpoint still requires X-Api-Key, so
    # exposing the schema itself leaks nothing sensitive.
    app = FastAPI(
        title="gplaces API",
        version="0.2.0",
        description=(
            "Self-hosted Google Places / Roads / Reviews proxy for omono. "
            "Every data endpoint requires `X-Api-Key`. "
            "Full reference: https://github.com/omarss/workspace/blob/main/gplaces_parser/README.md"
        ),
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        openapi_url="/v1/openapi.json",
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Flatten pydantic's structured errors into the single-string shape
        # FEEDBACK §3 mandates, so omono can show it to the user directly.
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

    if not settings.gplaces_api_key:
        raise SystemExit(
            "GPLACES_API_KEY is empty — set it in .env before starting the API."
        )
    uvicorn.run(
        "gplaces_parser.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
