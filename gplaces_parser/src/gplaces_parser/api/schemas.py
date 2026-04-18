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


class Road(BaseModel):
    osm_id: int
    name: str | None = None
    name_en: str | None = None
    highway: str
    ref: str | None = None
    maxspeed_kmh: int
    speed_source: str | None = None
    lanes: int | None = None
    oneway: bool | None = None
    # Bearing of the road's long axis in degrees, 0=N, 90=E, 180=S, 270=W.
    # Normalised to [0, 360); since a road is symmetric, clients pairing
    # against a GPS heading should match either `h` or `(h + 180) % 360`.
    heading_deg: float | None = None


class RoadsResponse(BaseModel):
    # Multiple matches are returned when the point sits at an intersection
    # (two polygons overlap). The client picks: highest-class, highest
    # maxspeed, whichever best matches its direction of travel, etc.
    roads: list[Road]
    source: str = "gplaces"
    generated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class SearchResult(BaseModel):
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
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    source: str = "gplaces"
    generated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
