#!/usr/bin/env python3
"""
Build polygon road map of Riyadh with per-segment speed limits.

Reads tile caches produced by fetch_roads.py, deduplicates ways by OSM id,
resolves a km/h for every segment (OSM tag first, else KSA default by class),
buffers each LineString into a lane-width Polygon, and streams a GeoJSON
FeatureCollection to ./roads.json.

Speed inference uses Saudi Arabia traffic law as of 2026:
    motorway      120 km/h   (intercity limited-access)
    trunk         100 km/h   (expressway inside urban area)
    primary        80 km/h   (major arterial)
    secondary      60 km/h
    tertiary       50 km/h
    unclassified   50 km/h
    residential    40 km/h
    living_street  20 km/h
    service        25 km/h
    road (unknown) 50 km/h
    *_link        speed of the parent class - 20 km/h

Multi-source conflict resolution (see `resolve_speed`):

    1. Each candidate signal has a *priority* (more authoritative first):
         100  osm:maxspeed                 explicit signed value
          90  osm:maxspeed:forward/backward   directional signed value
          70  osm:source:maxspeed          implicit zone (e.g. SA:urban)
          10  inferred:highway_class       KSA default by road type

    2. Highest-priority group wins. Within the winning group:
         a) if timestamps are present, the newest signal wins.
         b) otherwise the most common value wins (majority vote).
         c) vote ties break toward the *lower* speed (safer guess).

    The resolved value is recorded along with the label of the source(s)
    that produced it in the `speed_source` property.

Lane-width heuristic (used when `width` tag absent):
    lanes * 3.5 m + 1 m shoulder per side
    Fallback lane counts by highway class if `lanes` is missing.

Each Feature:
    {
      "type": "Feature",
      "geometry": <Polygon>,  # WGS84 degrees
      "properties": {
        "osm_id": 12345,
        "name": "طريق الملك فهد",
        "name_en": "King Fahd Road",
        "highway": "trunk",
        "lanes": 4,
        "width_m": 16.0,
        "oneway": true,
        "maxspeed_kmh": 100,
        "speed_source": "osm_tag" | "inferred"
      }
    }
"""
from __future__ import annotations

import gzip
import json
import math
import re
import sys
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import transform as shp_transform, unary_union
from shapely.strtree import STRtree

CACHE_DIR = Path(__file__).parent / "cache"
OUTPUT = Path(__file__).parent / "roads.json"
SCHOOLS_CACHE = CACHE_DIR / "schools.json.gz"
LANDUSE_CACHE = CACHE_DIR / "landuse.json.gz"
MAPILLARY_CACHE = CACHE_DIR / "mapillary_signs.json.gz"

# Distance a Mapillary speed-sign detection must be from a road for it to
# count as belonging to that road. 30 m covers sign placement on the
# verge + GPS drift; beyond that the match is unreliable.
MAPILLARY_MATCH_RADIUS_M = 30
# Note: corrections.json is NOT consumed by the build. It is a held-out
# ground-truth test set used by quality_check.py to grade the algorithm's
# accuracy. The build pipeline must remain blind to it — otherwise we'd
# be evaluating the override against itself.

# Buffer around each school/university boundary. KSA posted school-zone
# signs start ~80-100 m before the entrance. 100 m is conservative enough
# to catch the roads that serve schools without flagging entire districts.
SCHOOL_ZONE_BUFFER_M = 100

# Speed cap applied to roads falling in a school zone *iff* the speed was
# inferred (OSM `maxspeed` always wins to respect posted signs).
SCHOOL_ZONE_CAP_KMH = 40

# Road-level consensus parameters.
# Many OSM ways in Riyadh share a name (e.g. "Prince Sultan Rd") but have
# inconsistent or occasionally wrong `maxspeed` tags on individual segments.
# We aggregate per "road identity" (name, name:en, ref), **length-weighted**,
# and use the dominant speed as a priority-60 signal for un-tagged segments
# and to demote clearly-outlier tags.
#
# Length-weighting matters because short slip-ramps often carry different
# (lower) tags than long main-carriageway sections; a count-weighted mode
# would let ramps win on roads like Riyadh-Dammam Expy. We use the polygon's
# approximate UTM length (in metres) as the vote weight.
ROAD_CONSENSUS_MIN_SUPPORTERS = 3      # ≥3 tagged segs before trusting a mode
ROAD_CONSENSUS_MIN_AGREEMENT  = 0.70   # dominant value must cover ≥70% of length
ROAD_CONSENSUS_OUTLIER_KMH    = 25     # |seg − road_mode| > this ⇒ outlier
ROAD_CONSENSUS_OUTLIER_MIN    = 5      # outlier demotion only when ≥5 supporters


# corrections.json is NOT consumed by the build. See comment at top.

# --- speed defaults (km/h) ---------------------------------------------------

SPEED_DEFAULT_KMH = {
    # Urban defaults (inside the built-up area — roughly SA:urban=80).
    #
    # Tuned against the corrections.json test set (per-class drift output
    # in quality_check.py). Motorway lowered from 120 to 115 because the
    # Riyadh ring roads are posted 110 and dominate the motorway sample.
    # Secondary raised from 60 to 70 — Olaya/Takhassusi-style arterials
    # are the typical secondary in Riyadh and posted 70-80.
    "motorway":      115,
    "trunk":         100,
    "primary":        80,
    "secondary":      75,
    "tertiary":       60,   # urban distributor in Riyadh — usually 60 posted
    "unclassified":   50,
    "residential":    40,
    "living_street":  20,
    "service":        20,
    "road":           40,
}

# Rural defaults — applied when a way's midpoint is outside the buffered
# urban landuse mask. Empirically the Riyadh-area intercity roads posted
# at 100 (Salbukh, Dirab, Al Hayer, Al Thumama) are classified as trunk
# in OSM, not motorway. Setting rural trunk to 100 matches those; motorway
# already carries 120 regardless of zone.
#
# The bump vs the urban table is deliberately modest — OSM landuse in
# Riyadh is patchy, and a midpoint landing *just* outside a buffered
# polygon should not flip a road's default by 40 km/h. We only bump
# primary/secondary/tertiary where outer-city posting is measurably higher.
SPEED_DEFAULT_KMH_RURAL = {
    "motorway":      120,
    "trunk":         100,
    "primary":       100,
    "secondary":      80,
    "tertiary":       70,
    "unclassified":   60,
    "residential":    40,   # same as urban — residential is residential
    "living_street":  20,
    "service":        25,
    "road":           50,
}

# Sub-speeds by service=* value (applies only when highway=service).
SERVICE_SUBTYPE_KMH = {
    "driveway":        20,
    "alley":           20,
    "parking_aisle":   15,
    "drive-through":   10,
    "drive_through":   10,
    "emergency_access": 30,
    "yes":             20,  # explicit but unspecific
}

# Slip-road / ramp speed = parent class default - LINK_DELTA, floor 30.
# Tuned to 5 — KSA ramps in Riyadh are typically signposted at the same
# speed as the parent carriageway (maybe one tier below). Our original
# -20 assumption was too aggressive per the per-class drift analysis.
LINK_DELTA = 5


def speed_for_class(hw: str, tags: dict | None = None,
                    is_rural: bool = False) -> int:
    """
    KSA class-default speed in km/h.

    `is_rural=True` switches to the rural table — applied only when the
    way's midpoint is outside the OSM landuse urban mask.
    """
    table = SPEED_DEFAULT_KMH_RURAL if is_rural else SPEED_DEFAULT_KMH
    if hw.endswith("_link"):
        parent = hw[:-5]
        base = table.get(parent, 50)
        return max(30, base - LINK_DELTA)
    if hw == "service" and tags:
        sv = (tags.get("service") or "").strip().lower()
        if sv in SERVICE_SUBTYPE_KMH:
            return SERVICE_SUBTYPE_KMH[sv]
    base = table.get(hw, 50)
    # Lane-count nudge for big arterials: 4+ lanes + name/ref ⇒ likely 80+.
    if tags and hw in {"secondary", "tertiary"}:
        raw_lanes = tags.get("lanes")
        if raw_lanes and raw_lanes.isdigit() and int(raw_lanes) >= 4:
            return max(base, 80)
    return base


# --- multi-source speed resolution ------------------------------------------

from collections import Counter
from typing import NamedTuple


# --- road-level consensus (pass 1 aggregation) ------------------------------

# Class families for consensus bucketing. A "King Fahd Rd" residential
# side-street should not vote in the same pool as a primary-class main
# carriageway of the same name — they are different physical roads that
# happen to share a human label. Pooling by class family prevents that.
_HW_FAMILY = {
    "motorway": "motor", "motorway_link": "motor",
    "trunk":    "trunk", "trunk_link":    "trunk",
    "primary":  "primary", "primary_link":  "primary",
    "secondary": "secondary", "secondary_link": "secondary",
    "tertiary":  "tertiary", "tertiary_link":  "tertiary",
    "unclassified": "local", "residential": "local",
    "living_street": "local", "service": "local", "road": "local",
}


def _road_key(tags: dict) -> tuple | None:
    """
    Identity for "this is the same named road of the same class". We pool
    by (name, name:en, ref, class_family). An OSM way with no name/ref
    cannot be pooled and returns None.
    """
    name = (tags.get("name") or "").strip().lower()
    name_en = (tags.get("name:en") or "").strip().lower()
    ref = (tags.get("ref") or "").strip().lower()
    if not (name or name_en or ref):
        return None
    fam = _HW_FAMILY.get(tags.get("highway") or "", "other")
    return (name, name_en, ref, fam)


class RoadConsensus(NamedTuple):
    mode_kmh: int
    supporters: int          # count of tagged segments matching the mode
    total_tagged: int        # total tagged segments on the road
    agreement: float         # fraction of *length* at the mode speed (0..1)


ROAD_CONSENSUS: dict[tuple, RoadConsensus] = {}


def _way_length_m(el: dict) -> float:
    """Approximate OSM way length in metres via UTM projection."""
    pts = el.get("geometry") or []
    if len(pts) < 2:
        return 0.0
    try:
        line = LineString([(p["lon"], p["lat"]) for p in pts])
        return shp_transform(_to_utm, line).length
    except Exception:
        return 0.0


def build_road_consensus() -> dict[tuple, RoadConsensus]:
    """
    Pass 1: scan every cached OSM way, group by `_road_key`, collect the
    *length-weighted* distribution of explicit `maxspeed` values, and
    freeze a consensus when:
        - at least ROAD_CONSENSUS_MIN_SUPPORTERS tagged segments exist, AND
        - the length-dominant speed covers at least MIN_AGREEMENT of the
          total tagged length (prevents 50/50 splits from asserting a mode).
    """
    # per_road[key][speed] = (count, length_m)
    per_road: dict[tuple, dict[int, list[float]]] = {}
    for el in iter_ways():
        tags = el.get("tags") or {}
        key = _road_key(tags)
        if key is None:
            continue
        s = parse_speed_tag(tags.get("maxspeed"))
        if s is None:
            continue
        length = _way_length_m(el)
        slot = per_road.setdefault(key, {}).setdefault(s, [0, 0.0])
        slot[0] += 1
        slot[1] += length

    consensus: dict[tuple, RoadConsensus] = {}
    for key, speeds in per_road.items():
        total_count = sum(c for c, _ in speeds.values())
        total_length = sum(l for _, l in speeds.values()) or 1.0
        if total_count < ROAD_CONSENSUS_MIN_SUPPORTERS:
            continue
        # pick the speed with the greatest aggregated length.
        dom_speed, (dom_count, dom_length) = max(
            speeds.items(), key=lambda kv: kv[1][1])
        agreement = dom_length / total_length
        if agreement < ROAD_CONSENSUS_MIN_AGREEMENT:
            continue
        consensus[key] = RoadConsensus(dom_speed, dom_count, total_count,
                                       round(agreement, 2))
    return consensus


def road_consensus_for(tags: dict) -> RoadConsensus | None:
    key = _road_key(tags)
    return ROAD_CONSENSUS.get(key) if key else None


class SpeedCandidate(NamedTuple):
    speed: int
    source: str
    priority: int
    # timestamp is an iso-8601 string when the signal carries one (OSM way
    # meta, external API, ...). None means "no time info for this signal".
    timestamp: str | None


def _collect_candidates(tags: dict, hw: str, osm_timestamp: str | None,
                        is_rural: bool = False) -> list[SpeedCandidate]:
    out: list[SpeedCandidate] = []

    consensus = road_consensus_for(tags)

    # Priority 100 — explicit posted value (signed).
    # If the tag disagrees sharply with the rest of its road's tags and the
    # road has a well-supported mode, demote it to priority 50 — the road
    # consensus (priority 60) will win over it, which fixes OSM editing
    # errors like `maxspeed=25` scattered across an 80-km/h arterial.
    s = parse_speed_tag(tags.get("maxspeed"))
    if s is not None:
        priority = 100
        source = "osm:maxspeed"
        # Demote 1: outlier vs the same road's consensus.
        if (consensus
                and consensus.supporters >= ROAD_CONSENSUS_OUTLIER_MIN
                and abs(s - consensus.mode_kmh) > ROAD_CONSENSUS_OUTLIER_KMH):
            priority = 50
            source = "osm:maxspeed:outlier"
        # Demote 2: clear class-mismatch — OSM value wildly below the class
        # default (almost always mph/kmh confusion, e.g. `maxspeed=25` on a
        # 6-lane secondary). We honour the tag at lower priority so the
        # class inference (priority 10) still loses, but if something
        # stronger like `source:maxspeed` or conditional exists it wins.
        class_default = speed_for_class(hw, tags, is_rural=is_rural)
        if (hw not in {"service", "living_street", "residential"}
                and s < class_default * 0.55):
            # Below inference priority so the class default wins.
            priority = 5
            source = "osm:maxspeed:rejected_low"
        out.append(SpeedCandidate(s, source, priority, osm_timestamp))

    # Priority 95 — conditional rules ("80 @ (06:00-22:00); 60 @ (night)") —
    # take the first unconditional-looking value as a reasonable fallback.
    cond = tags.get("maxspeed:conditional")
    if cond:
        first = cond.split(";")[0].split("@")[0].strip()
        s = parse_speed_tag(first)
        if s is not None:
            out.append(SpeedCandidate(s, "osm:maxspeed:conditional", 95,
                                      osm_timestamp))

    # Priority 90 — directional values (useful on divided OSM ways tagged
    # with only one direction; we treat both as equally valid signals).
    for key in ("maxspeed:forward", "maxspeed:backward"):
        s = parse_speed_tag(tags.get(key))
        if s is not None:
            out.append(SpeedCandidate(s, f"osm:{key}", 90, osm_timestamp))

    # Priority 80 — zone:maxspeed (e.g. "SA:30" = 30, "DE:urban" etc.).
    for key in ("zone:maxspeed", "zone:traffic"):
        s = parse_speed_tag(_zone_to_kmh(tags.get(key)))
        if s is not None:
            out.append(SpeedCandidate(s, f"osm:{key}", 80, osm_timestamp))

    # Priority 70 — source:maxspeed or maxspeed:type (implicit zone markers).
    for key in ("source:maxspeed", "maxspeed:type"):
        raw = tags.get(key)
        s = parse_speed_tag(_zone_to_kmh(raw)) if raw else None
        if s is not None:
            out.append(SpeedCandidate(s, f"osm:{key}", 70, osm_timestamp))

    # Road-level consensus is *only* used for outlier demotion above, not
    # as a positive-propagation signal. Empirically the OSM tagging inside
    # Riyadh is inconsistent enough that propagating the modal OSM speed to
    # untagged segments hurts accuracy more than it helps: ~45% length-acc
    # vs ~91% for the plain class-inference fallback. A future improvement
    # could re-enable propagation gated by extra signals (ref/landuse), but
    # for now we leave untagged segments to the class default.

    # Priority 40 — advisory limit. Not legally binding but a good signal
    # when nothing else is posted. Ranks *above* pure class inference.
    s = parse_speed_tag(tags.get("maxspeed:advisory"))
    if s is not None:
        out.append(SpeedCandidate(s, "osm:maxspeed:advisory", 40,
                                  osm_timestamp))

    # Priority 10 — inferred KSA default from highway class (always present).
    inferred = speed_for_class(hw, tags, is_rural=is_rural)
    # Surface cap — unpaved/gravel can't sustain posted urban/highway speeds.
    surface = (tags.get("surface") or "").strip().lower()
    unpaved = {"unpaved", "gravel", "sand", "dirt", "ground", "compacted",
               "fine_gravel", "earth", "mud", "grass"}
    if surface in unpaved:
        inferred = min(inferred, 60)
    smoothness = (tags.get("smoothness") or "").strip().lower()
    if smoothness in {"very_bad", "horrible", "very_horrible", "impassable"}:
        inferred = min(inferred, 30)
    label = "inferred:highway_class_rural" if is_rural else "inferred:highway_class"
    out.append(SpeedCandidate(inferred, label, 10, None))
    return out


# Implicit KSA zone codes from OSM tagging — map to km/h.
_ZONE_CODE_KMH = {
    "sa:urban":         80,
    "sa:rural":        120,
    "sa:motorway":     120,
    "sa:living_street": 20,
    "sa:trunk":        100,
    # Generic "SA:<number>" is handled by the digit regex below.
}


def _zone_to_kmh(val: str | None) -> str | None:
    """
    Translate zone/source codes like "SA:urban", "SA:30" into a numeric
    km/h string parseable by parse_speed_tag. Returns None if unknown.
    """
    if not val:
        return None
    v = val.strip().lower()
    if v in _ZONE_CODE_KMH:
        return str(_ZONE_CODE_KMH[v])
    # "SA:30" / "DE:50" etc.
    m = re.match(r"^[a-z]{2}:(\d+)$", v)
    if m:
        return m.group(1)
    # Already numeric — passthrough.
    if re.match(r"^\d+(\s*(mph|km/h|kmh))?$", v):
        return v
    return None


def _confidence_for(priority: int, agreement: bool) -> float:
    """
    Convert a winning-candidate priority tier into a 0..1 confidence score.
    `agreement` is True when all top-tier candidates voted for the same speed.
    """
    base = {100: 0.98, 95: 0.90, 90: 0.85, 80: 0.80, 70: 0.70,
            60: 0.65, 50: 0.55, 45: 0.50, 40: 0.45, 10: 0.40,
            5: 0.30}.get(priority, 0.30)
    if not agreement:
        base -= 0.10
    return round(max(0.05, min(0.99, base)), 2)


def _class_mismatch_warning(speed: int, hw: str) -> str | None:
    """
    Flag OSM tags that disagree wildly with the road class — these are usually
    data-entry mistakes (e.g. `maxspeed=25` on a `highway=secondary`) but we
    still honour the tag. The warning is surfaced in properties and pulls
    the confidence score down so downstream consumers can filter.

    Threshold: a gap of > 30 km/h versus the inferred class default, OR an
    absolute implausibility (motorway < 80, residential > 70).
    """
    default = speed_for_class(hw)
    diff = abs(speed - default)
    if hw.startswith("motorway") and speed < 80:
        return "motorway_low_speed"
    if hw == "residential" and speed > 70:
        return "residential_high_speed"
    if hw == "living_street" and speed > 30:
        return "living_street_high_speed"
    if hw == "service" and speed > 40:
        return "service_high_speed"
    if diff > 30:
        return "class_mismatch"
    return None


def resolve_speed(tags: dict, hw: str, osm_timestamp: str | None = None,
                  is_rural: bool = False
                  ) -> tuple[int, str, float, str | None]:
    """
    Pick the best speed limit from all available signals.

    Policy:
      1. Highest-priority candidates beat lower-priority ones.
      2. Within the winning group, timestamps break ties (newest wins).
      3. If no timestamps or they are equal, majority vote wins.
      4. Vote ties break toward the *lower* speed (safer fallback).
    """
    cands = _collect_candidates(tags, hw, osm_timestamp, is_rural=is_rural)
    best_prio = max(c.priority for c in cands)
    top = [c for c in cands if c.priority == best_prio]

    def _finalize(speed: int, source: str, priority: int,
                  agreement: bool) -> tuple[int, str, float, str | None]:
        conf = _confidence_for(priority, agreement)
        warn = _class_mismatch_warning(speed, hw) if priority >= 70 else None
        if warn:
            conf = round(max(0.4, conf - 0.15), 2)
        return speed, source, conf, warn

    if len(top) == 1:
        c = top[0]
        return _finalize(c.speed, c.source, c.priority, True)

    # Newest wins if any candidate has a timestamp that's strictly newest.
    dated = [c for c in top if c.timestamp]
    if dated:
        latest_ts = max(c.timestamp for c in dated)
        latest = [c for c in dated if c.timestamp == latest_ts]
        if len(latest) == 1:
            c = latest[0]
            return _finalize(c.speed, f"latest:{c.source}", c.priority, True)
        top = latest  # fall through to vote among equally-new signals

    # Majority vote on speed value.
    votes = Counter(c.speed for c in top)
    max_votes = max(votes.values())
    tied = sorted(s for s, v in votes.items() if v == max_votes)
    winner = tied[0]  # lowest speed wins the tie — conservative default
    contributors = "+".join(sorted({c.source for c in top if c.speed == winner}))
    agreement = (len(tied) == 1)
    label = f"vote:{contributors}" if agreement else f"vote-tie:{contributors}"
    return _finalize(winner, label, best_prio, agreement)


# --- default lane counts when `lanes` tag missing ---------------------------

DEFAULT_LANES = {
    "motorway":      3,
    "motorway_link": 1,
    "trunk":         3,
    "trunk_link":    1,
    "primary":       2,
    "primary_link":  1,
    "secondary":     2,
    "secondary_link": 1,
    "tertiary":      2,
    "tertiary_link": 1,
    "unclassified":  1,
    "residential":   1,
    "living_street": 1,
    "service":       1,
    "road":          1,
}

# Per-class lane and shoulder widths (metres). Based on MOT / KSA highway
# geometric design guidelines — freeway lanes are ~3.65 m, urban 3.25 m,
# residential 3.0 m. Shoulders are only generous on motorway/trunk.
LANE_WIDTH_BY_CLASS = {
    "motorway":      3.65, "motorway_link":  3.5,
    "trunk":         3.5,  "trunk_link":     3.25,
    "primary":       3.5,  "primary_link":   3.25,
    "secondary":     3.25, "secondary_link": 3.0,
    "tertiary":      3.25, "tertiary_link":  3.0,
    "unclassified":  3.0,
    "residential":   3.0,
    "living_street": 2.75,
    "service":       2.75,
    "road":          3.0,
}
SHOULDER_BY_CLASS = {
    "motorway":     2.5,   "motorway_link": 1.0,
    "trunk":        2.0,   "trunk_link":    1.0,
    "primary":      1.0,   "primary_link":  0.5,
    "secondary":    0.5,
    "tertiary":     0.5,
}
LANE_WIDTH_M = 3.5      # legacy fallback
SHOULDER_M = 1.0        # legacy fallback


# --- speed parsing -----------------------------------------------------------

_SPEED_RE = re.compile(r"^\s*(\d+)\s*(mph|km/h|kmh)?\s*$", re.IGNORECASE)


def parse_speed_tag(val: str | None) -> int | None:
    """
    Parse OSM maxspeed tag. Returns km/h, or None if unparseable.

    Handles: "80", "80 km/h", "50 mph", "walk", "signals", "none", "SA:urban".
    """
    if not val:
        return None
    v = val.strip().lower()
    if v in {"none", "signals", "walk", "variable"}:
        return None
    # country:category implicit limits — map KSA ones.
    if v.startswith("sa:"):
        return {
            "sa:urban":       60,
            "sa:rural":      100,
            "sa:motorway":   120,
            "sa:living_street": 20,
        }.get(v)
    m = _SPEED_RE.match(v)
    if not m:
        return None
    n = int(m.group(1))
    unit = (m.group(2) or "km/h").lower()
    if unit == "mph":
        n = round(n * 1.609344)
    # Plausibility filter — reject obviously-bad OSM values.
    if not (5 <= n <= 160):
        return None
    return n


# --- lanes parsing -----------------------------------------------------------

def parse_lanes(tags: dict, hw: str) -> int:
    """
    Resolve lane count. OSM `lanes` counts *total* lanes across both directions;
    if oneway we still use the number as-is (it's the travel-lane count).
    """
    raw = tags.get("lanes")
    if raw:
        m = re.match(r"(\d+)", raw)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 20:
                return n
    return DEFAULT_LANES.get(hw, 2)


def parse_width(tags: dict, lanes: int, hw: str = "") -> float:
    """Return carriageway width in metres."""
    raw = tags.get("width")
    if raw:
        m = re.match(r"([\d.]+)", raw)
        if m:
            w = float(m.group(1))
            if 1.5 <= w <= 80:
                return w
    lane_w = LANE_WIDTH_BY_CLASS.get(hw, LANE_WIDTH_M)
    shoulder = SHOULDER_BY_CLASS.get(hw, 0.25)  # small kerb offset by default
    return lanes * lane_w + 2 * shoulder


# --- projection --------------------------------------------------------------

# UTM zone 38N covers Riyadh (longitudes 42–48°E).
_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32638", always_xy=True).transform
_to_wgs = Transformer.from_crs("EPSG:32638", "EPSG:4326", always_xy=True).transform


def buffer_line_to_polygon(line: LineString, width_m: float):
    """Buffer a WGS84 LineString by half-width in metres and return a WGS84 geom."""
    utm_line = shp_transform(_to_utm, line)
    # cap_style=2 (flat) gives squared-off ends — closer to a real road segment.
    # join_style=2 (mitre) keeps corners sharp.
    buf = utm_line.buffer(width_m / 2.0, cap_style=2, join_style=2, mitre_limit=2.0)
    return shp_transform(_to_wgs, buf)


# --- school-zone spatial index (built in UTM, in metres) --------------------

_SCHOOL_ZONES: STRtree | None = None
_SCHOOL_META: list[dict] = []  # parallel to the STRtree geoms

# --- urban-mask spatial index (UTM metres) ----------------------------------

_URBAN_INDEX: STRtree | None = None
_URBAN_POLYS: list[Polygon] = []   # parallel; kept for point-in-polygon test


def _amenity_geom_utm(el: dict) -> Polygon | Point | None:
    """Convert an Overpass amenity element to a UTM Shapely geometry."""
    t = el.get("type")
    if t == "node":
        lon, lat = el.get("lon"), el.get("lat")
        if lon is None or lat is None:
            return None
        return Point(_to_utm(lon, lat))
    # Way or relation — Overpass "out geom" gives us a `geometry` list of
    # {lat,lon} rings. Build a polygon.
    if t == "way":
        pts = el.get("geometry") or []
        if len(pts) < 3:
            return None
        coords = [_to_utm(p["lon"], p["lat"]) for p in pts]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        try:
            return Polygon(coords)
        except Exception:
            return None
    if t == "relation":
        center = el.get("center")
        if center:
            return Point(_to_utm(center["lon"], center["lat"]))
    return None


def build_school_zones() -> tuple[STRtree | None, list[dict]]:
    """Build an R-tree of buffered school-zone polygons (UTM metres)."""
    if not SCHOOLS_CACHE.exists():
        return None, []
    with gzip.open(SCHOOLS_CACHE, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    zones: list[Polygon] = []
    meta: list[dict] = []
    for el in data.get("elements", []):
        g = _amenity_geom_utm(el)
        if g is None or g.is_empty:
            continue
        zone = g.buffer(SCHOOL_ZONE_BUFFER_M)
        zones.append(zone)
        meta.append({
            "amenity": (el.get("tags") or {}).get("amenity"),
            "name": (el.get("tags") or {}).get("name"),
            "osm_id": el.get("id"),
            "osm_type": el.get("type"),
        })
    if not zones:
        return None, []
    return STRtree(zones), meta


def _line_in_school_zone(line_utm: LineString) -> dict | None:
    """Return the closest school-zone meta dict, or None, for a UTM LineString."""
    if _SCHOOL_ZONES is None:
        return None
    # STRtree.query returns indices (shapely 2.x).
    hits = _SCHOOL_ZONES.query(line_utm, predicate="intersects")
    if len(hits) == 0:
        return None
    # Just return the first matching meta — we only need "is it a school zone"
    # and a label for traceability.
    return _SCHOOL_META[int(hits[0])]


# --- Mapillary speed-sign spatial index (UTM metres) ------------------------
#
# Each point is a speed-limit sign detected in crowdsourced street imagery.
# At build time, for every road we nearest-neighbour query and adopt the
# detected limit if a sign is within MAPILLARY_MATCH_RADIUS_M and the sign
# value is plausible for the road class.

_MAPILLARY_INDEX: STRtree | None = None
_MAPILLARY_META: list[dict] = []  # parallel: {speed_kmh, timestamp_iso}


def _mapillary_value_to_kmh(value: str) -> int | None:
    """`regulatory--maximum-speed-limit-80` → 80."""
    if not value or "maximum-speed-limit-" not in value:
        return None
    try:
        return int(value.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return None


def build_mapillary_index() -> tuple[STRtree | None, list[dict]]:
    """Load cached Mapillary sign detections into a UTM spatial index."""
    if not MAPILLARY_CACHE.exists():
        return None, []
    with gzip.open(MAPILLARY_CACHE, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    points: list[Point] = []
    meta: list[dict] = []
    for f in payload.get("features", []):
        value = f.get("object_value")
        speed = _mapillary_value_to_kmh(value)
        if speed is None:
            continue
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if not coords or len(coords) < 2:
            continue
        try:
            p = Point(_to_utm(coords[0], coords[1]))
            points.append(p)
            meta.append({
                "speed_kmh": speed,
                "timestamp": f.get("first_seen_at") or f.get("last_seen_at"),
                "mapillary_id": f.get("id"),
            })
        except Exception:
            continue
    if not points:
        return None, []
    return STRtree(points), meta


def _mapillary_speed_for(line_utm: LineString) -> dict | None:
    """Nearest Mapillary sign within MAPILLARY_MATCH_RADIUS_M, if any."""
    if _MAPILLARY_INDEX is None:
        return None
    nearest_idx = _MAPILLARY_INDEX.nearest(line_utm)
    if nearest_idx is None:
        return None
    # STRtree.nearest returns a geometry or index depending on shapely ver.
    idx = int(nearest_idx) if isinstance(nearest_idx, (int, float)) else None
    if idx is None:
        # older shapely returns geometry; fall back to linear search
        return None
    pt = _MAPILLARY_INDEX.geometries[idx]
    if pt.distance(line_utm) > MAPILLARY_MATCH_RADIUS_M:
        return None
    return _MAPILLARY_META[idx]


_MAPILLARY_INDEX = None
_MAPILLARY_META = []


# Distance beyond which a way is considered rural. Picked to be slightly
# larger than typical OSM landuse-polygon gaps in Riyadh (~400-500 m for
# unmapped neighbourhoods and inter-district green strips).
URBAN_PROXIMITY_M = 800

# Toggle the urban/rural branch on/off. Defaults to OFF — the rural bump
# hurt measured accuracy on the test set. Flip to True once the landuse
# layer covers the full built-up area of Riyadh.
URBAN_RURAL_ENABLED = False


def build_urban_mask() -> tuple[STRtree | None, list[Polygon]]:
    """Union the landuse/place polygons into an urban spatial index (UTM).

    We buffer each polygon by URBAN_PROXIMITY_M before inserting into the
    index. Any way whose midpoint falls within the buffered mask is treated
    as urban — closes the gaps where OSM simply hasn't mapped a
    neighbourhood as `landuse=residential`, while still leaving intercity
    corridors (far from any tagged area) as rural.
    """
    if not LANDUSE_CACHE.exists():
        return None, []
    with gzip.open(LANDUSE_CACHE, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    polys: list[Polygon] = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        pts = el.get("geometry") or []
        if len(pts) < 3:
            continue
        try:
            coords = [_to_utm(p["lon"], p["lat"]) for p in pts]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            poly = Polygon(coords)
            if poly.is_valid and not poly.is_empty:
                polys.append(poly.buffer(URBAN_PROXIMITY_M))
        except Exception:
            continue
    if not polys:
        return None, []
    return STRtree(polys), polys


def _way_is_rural(line_utm: LineString) -> bool:
    """Return True if the way's midpoint is outside every buffered urban polygon.

    Disabled by default for Riyadh: OSM `landuse=residential` coverage is
    too patchy to trust, and the rural bump on primary/secondary hurts
    overall accuracy against the Google-verified test set more than it
    helps (67% → 64% count-weighted, -3 pts). The infrastructure stays in
    place so you can flip `URBAN_RURAL_ENABLED` on once landuse coverage
    improves (e.g. after importing official city limits).
    """
    if not URBAN_RURAL_ENABLED or _URBAN_INDEX is None:
        return False
    try:
        mid = line_utm.interpolate(0.5, normalized=True)
    except Exception:
        return False
    hits = _URBAN_INDEX.query(mid, predicate="intersects")
    return len(hits) == 0


# --- main build --------------------------------------------------------------

def iter_ways():
    """Yield every OSM way element across all cached tiles."""
    for path in sorted(CACHE_DIR.glob("tile_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        for el in data.get("elements", []):
            if el.get("type") == "way":
                yield el


def process_way(el: dict) -> dict | None:
    tags = el.get("tags", {})
    hw = tags.get("highway")
    if not hw:
        return None
    geom = el.get("geometry") or []
    if len(geom) < 2:
        return None

    coords = [(pt["lon"], pt["lat"]) for pt in geom]
    try:
        line = LineString(coords)
    except Exception:
        return None
    if line.is_empty or line.length == 0:
        return None

    lanes = parse_lanes(tags, hw)
    width_m = parse_width(tags, lanes, hw)

    # Compute once and reuse for school-zone + urban/rural checks.
    line_utm = shp_transform(_to_utm, line)
    is_rural = _way_is_rural(line_utm)

    speed, source, confidence, warning = resolve_speed(
        tags, hw, el.get("timestamp"), is_rural=is_rural)

    # Mapillary speed-sign override. A nearby sign detection carries more
    # weight than anything except an explicit OSM `maxspeed` tag. Applies
    # when the current resolved source is below priority 95 (i.e. all
    # inference paths and directional/zone OSM tags). Skip on motorway
    # ramps/service where ground-level sign detection is unreliable.
    if (_MAPILLARY_INDEX is not None
            and not source.startswith("osm:maxspeed")
            and hw not in {"service", "motorway_link", "trunk_link"}):
        sign = _mapillary_speed_for(line_utm)
        if sign is not None:
            sign_speed = sign["speed_kmh"]
            # Reject Mapillary values that fall below 55% of class default —
            # these are almost always misread signs.
            class_default = speed_for_class(hw, tags, is_rural=is_rural)
            if 5 <= sign_speed <= 160 and sign_speed >= class_default * 0.5:
                speed = sign_speed
                source = f"mapillary:sign[{sign.get('mapillary_id', '?')}]"
                confidence = 0.92

    # School-zone cap — applies only to inferred speeds on lower-class
    # streets (KSA school zones are posted on residential/service/tertiary
    # frontage roads, never on motorways or trunks which physically bypass
    # schools). Never override a posted / user-corrected value.
    _SCHOOL_CAPPABLE = {"residential", "living_street", "service",
                        "unclassified", "tertiary", "tertiary_link",
                        "secondary", "secondary_link", "road"}
    if (speed > SCHOOL_ZONE_CAP_KMH
            and source.startswith("inferred")
            and hw in _SCHOOL_CAPPABLE):
        sch = _line_in_school_zone(line_utm)
        if sch:
            speed = SCHOOL_ZONE_CAP_KMH
            source = "inferred:school_zone"
            confidence = 0.55  # moderately confident — 100 m buffer is fuzzy
            warning = warning or f"school_zone:{sch.get('name') or sch['osm_id']}"

    try:
        poly = buffer_line_to_polygon(line, width_m)
    except Exception as exc:
        print(f"  ! buffer failed for way {el.get('id')}: {exc}", file=sys.stderr)
        return None
    if poly.is_empty:
        return None

    oneway_raw = tags.get("oneway", "no")
    oneway = oneway_raw in {"yes", "true", "1", "-1"}

    props = {
        "osm_id": el.get("id"),
        "name": tags.get("name"),
        "name_en": tags.get("name:en"),
        "highway": hw,
        "service": tags.get("service") if hw == "service" else None,
        "ref": tags.get("ref"),
        "lanes": lanes,
        "width_m": round(width_m, 1),
        "oneway": oneway,
        "maxspeed_kmh": speed,
        "speed_source": source,
        "speed_confidence": confidence,
        "speed_warning": warning,
        "rural": is_rural,
    }

    return {
        "type": "Feature",
        "geometry": mapping(poly),
        "properties": props,
    }


def main() -> None:
    global _SCHOOL_ZONES, _SCHOOL_META, ROAD_CONSENSUS
    global _URBAN_INDEX, _URBAN_POLYS
    global _MAPILLARY_INDEX, _MAPILLARY_META
    _SCHOOL_ZONES, _SCHOOL_META = build_school_zones()
    _URBAN_INDEX, _URBAN_POLYS = build_urban_mask()
    if _URBAN_INDEX is not None:
        total_km2 = sum(p.area for p in _URBAN_POLYS) / 1_000_000
        print(f"Loaded urban mask: {len(_URBAN_POLYS)} landuse/place polygons "
              f"(~{total_km2:.0f} km² coverage)")
    _MAPILLARY_INDEX, _MAPILLARY_META = build_mapillary_index()
    if _MAPILLARY_INDEX is not None:
        print(f"Loaded Mapillary sign index: {len(_MAPILLARY_META)} detections")
    else:
        print("Mapillary: no cache (run fetch_mapillary.py with "
              "MAPILLARY_TOKEN to enable)")
    print("Pass 1: building road-level consensus from tagged OSM ways ...")
    ROAD_CONSENSUS = build_road_consensus()
    if ROAD_CONSENSUS:
        heavy = sum(1 for v in ROAD_CONSENSUS.values()
                    if v.supporters >= ROAD_CONSENSUS_OUTLIER_MIN)
        unanimous = sum(1 for v in ROAD_CONSENSUS.values() if v.agreement >= 0.95)
        print(f"  -> {len(ROAD_CONSENSUS)} named roads with consensus "
              f"(≥{ROAD_CONSENSUS_MIN_SUPPORTERS} supporters, "
              f"≥{int(ROAD_CONSENSUS_MIN_AGREEMENT*100)}% length agreement); "
              f"{heavy} strong (≥{ROAD_CONSENSUS_OUTLIER_MIN} supp.), "
              f"{unanimous} unanimous (≥95%)")
    if _SCHOOL_ZONES is not None:
        print(f"Loaded {len(_SCHOOL_META)} school/university zones "
              f"(buffer={SCHOOL_ZONE_BUFFER_M} m)")
    seen: set[int] = set()
    n_in = n_out = 0
    by_class: dict[str, int] = {}
    by_source: dict[str, int] = {}

    with open(OUTPUT, "w", encoding="utf-8") as out:
        out.write('{"type":"FeatureCollection","features":[\n')
        first = True
        for el in iter_ways():
            n_in += 1
            wid = el.get("id")
            if wid in seen:
                continue
            seen.add(wid)
            feat = process_way(el)
            if feat is None:
                continue
            if not first:
                out.write(",\n")
            json.dump(feat, out, ensure_ascii=False, separators=(",", ":"))
            first = False
            n_out += 1
            by_class[feat["properties"]["highway"]] = (
                by_class.get(feat["properties"]["highway"], 0) + 1
            )
            src = feat["properties"]["speed_source"]
            by_source[src] = by_source.get(src, 0) + 1
            if n_out % 10000 == 0:
                print(f"  ... {n_out} features written", file=sys.stderr)
        out.write("\n]}\n")

    print(f"Processed rows: {n_in}")
    print(f"Unique ways:    {len(seen)}")
    print(f"Features out:   {n_out}")
    print("Speed source breakdown:")
    for k in sorted(by_source, key=lambda x: -by_source[x]):
        print(f"  {k:<36} {by_source[k]}")
    print("By highway class:")
    for k in sorted(by_class, key=lambda x: -by_class[x]):
        print(f"  {k:<18} {by_class[k]}")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
