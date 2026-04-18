"""Grid tiling over a WGS84 bounding box.

Outscraper's `coordinates` accepts one lat/lng per query; the search spreads
outward from that point up to roughly `search_radius_km`. We tile Riyadh into
cells spaced ~`tile_km` apart so adjacent circles overlap by ~20%, guaranteeing
coverage without excessive duplication (deduped by place_id downstream).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Tile:
    lat: float
    lng: float

    def coords(self) -> str:
        """Outscraper expects `"lat,lng"` as a string."""
        return f"{self.lat:.6f},{self.lng:.6f}"


def tile_grid(
    lat_min: float,
    lat_max: float,
    lng_min: float,
    lng_max: float,
    spacing_km: float,
) -> list[Tile]:
    # 1 deg latitude ≈ 111.32 km everywhere. Longitude shrinks with cos(lat).
    mid_lat = (lat_min + lat_max) / 2
    dlat = spacing_km / 111.32
    dlng = spacing_km / (111.32 * math.cos(math.radians(mid_lat)))

    tiles: list[Tile] = []
    lat = lat_min + dlat / 2  # center of first cell
    while lat <= lat_max:
        lng = lng_min + dlng / 2
        while lng <= lng_max:
            tiles.append(Tile(lat=round(lat, 6), lng=round(lng, 6)))
            lng += dlng
        lat += dlat
    return tiles
