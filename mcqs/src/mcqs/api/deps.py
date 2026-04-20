"""FastAPI dependencies — auth."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from ..config import settings


async def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Constant-time comparison so timing can't distinguish missing vs. wrong."""
    expected = settings.mcqs_api_key
    ok = bool(expected) and x_api_key is not None and hmac.compare_digest(x_api_key, expected)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
        )


AuthDep = Annotated[None, Depends(require_api_key)]
