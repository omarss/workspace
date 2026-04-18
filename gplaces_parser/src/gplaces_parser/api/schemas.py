"""Response schemas — shape locked to FEEDBACK.md §3."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NearbyResult(BaseModel):
    id: str
    name: str
    name_ar: str | None = None
    category: str
    lat: float
    lon: float
    address: str | None = None
    phone: str | None = None
    rating: float | None = None
    review_count: int | None = None
    open_now: bool | None = None
    website: str | None = None


class NearbyResponse(BaseModel):
    results: list[NearbyResult]
    source: str = "gplaces"
    generated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class Error(BaseModel):
    error: str
