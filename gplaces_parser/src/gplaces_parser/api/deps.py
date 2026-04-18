"""FastAPI dependencies — auth and DB."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

from ..config import settings


async def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Constant-time comparison so timing leaks don't tell missing vs. wrong."""
    expected = settings.gplaces_api_key
    ok = bool(expected) and x_api_key is not None and hmac.compare_digest(x_api_key, expected)
    if not ok:
        # Same 401 body regardless of missing vs. wrong (FEEDBACK §2).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
        )


AuthDep = Annotated[None, Depends(require_api_key)]


def error_json(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})
