#!/usr/bin/env python3
"""
Grade the speed-limit algorithm in build_roads.py against the held-out
ground-truth test set in corrections.json.

The build pipeline itself is blind to corrections.json — it resolves
speeds purely from OSM tags, KSA implicit zones, class inference, and
school-zone capping. This script then measures how well those signals
agree with the user-verified posted values in corrections.json.

Outputs, per rule:
  * mode, mean, median assigned speed
  * % of matching segments within tolerance of the posted ground truth
  * a per-source accuracy breakdown so we can see which signals agree
    or disagree with the posted truth
  * overall accuracy score
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32638", always_xy=True).transform

ROADS = Path(__file__).parent / "roads.json"
CORRECTIONS = Path(__file__).parent / "corrections.json"

# Default agreement tolerance when a rule doesn't specify one (km/h).
DEFAULT_TOLERANCE_KMH = 15

ALLOWED_HW = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential",
    "living_street", "service", "road",
}


def load_ground_truth() -> list[dict]:
    if not CORRECTIONS.exists():
        return []
    with open(CORRECTIONS, encoding="utf-8") as fh:
        data = json.load(fh)
    rules = data.get("corrections", []) if isinstance(data, dict) else []
    for r in rules:
        r["_subs_lower"] = [s.lower() for s in r.get("name_contains", [])]
        r["_hw_set"] = set(r.get("highway") or [])
        r.setdefault("tolerance_kmh", DEFAULT_TOLERANCE_KMH)
    return rules


def matches_rule(props: dict, rule: dict) -> bool:
    if rule["_hw_set"] and props["highway"] not in rule["_hw_set"]:
        return False
    combined = ((props.get("name") or "") + "|"
                + (props.get("name_en") or "")).lower()
    return any(s in combined for s in rule["_subs_lower"])


def polygon_area_m2(feature: dict) -> float:
    """Project the WGS84 Polygon into UTM metres and return its area (m²).
    This is used as a length-weighting proxy so a 2 km arterial counts far
    more than a 30 m slip-road piece.
    """
    try:
        poly = shape(feature["geometry"])
        return shp_transform(_to_utm, poly).area
    except Exception:
        return 0.0


def _source_family(src: str) -> str:
    """Bucket a `speed_source` label into a coarse family name.

    Examples:
      'osm:maxspeed'                       -> 'osm'
      'osm:maxspeed:outlier'               -> 'osm_outlier'
      'road_consensus[n=5/8]'              -> 'road_consensus'
      'inferred:highway_class'             -> 'inferred'
      'inferred:school_zone'               -> 'inferred_school'
      'vote:osm:maxspeed+osm:advisory'     -> 'vote'
    """
    if not src:
        return "unknown"
    head = src.split("[", 1)[0]        # drop road_consensus[...] bracket
    if src.startswith("osm:maxspeed:outlier"):
        return "osm_outlier"
    if src.startswith("osm:maxspeed:rejected"):
        return "osm_rejected"
    if src.startswith("inferred:school_zone"):
        return "inferred_school"
    if src.startswith("road_consensus"):
        return "road_consensus"
    return head.split(":", 1)[0]


def main() -> None:
    print(f"Loading {ROADS} ...")
    with open(ROADS, encoding="utf-8") as fh:
        data = json.load(fh)
    feats = data["features"]
    print(f"Features: {len(feats):,}")

    rules = load_ground_truth()
    if not rules:
        print("No corrections.json — nothing to grade.")
        return

    # ---- invariants -------------------------------------------------------
    errors = Counter()
    for f in feats:
        p = f["properties"]
        g = f["geometry"]
        if g["type"] != "Polygon":
            errors["non_polygon"] += 1; continue
        try:
            poly = shape(g)
        except Exception:
            errors["geom_parse"] += 1; continue
        if poly.is_empty or not poly.is_valid:
            errors["invalid_geom"] += 1
        if not (5 <= p["maxspeed_kmh"] <= 160):
            errors["speed_oor"] += 1
        if not (1.5 <= p["width_m"] <= 80):
            errors["width_oor"] += 1
        if p["highway"] not in ALLOWED_HW:
            errors["highway_unknown"] += 1
    print("\nInvariant violations:")
    if not errors:
        print("  (none)")
    for k, v in errors.items():
        print(f"  {k:<22} {v}")

    # Pre-compute area for every feature once — used for length-weighted
    # accuracy (rule segments are weighted by their polygon area, which is
    # ~proportional to segment length × carriageway width).
    areas = [polygon_area_m2(f) for f in feats]

    # ---- per-rule grading -------------------------------------------------
    print("\nGround-truth grading (corrections.json as held-out test set):")
    print(f"  {'label':<42} {'n':>5} {'len(km)':>8} {'expected':>9} {'mode':>5} "
          f"{'w.mean':>6} {'|Δ|':>4} {'±tol':>5} {'n-acc':>6} {'L-acc':>6}  verdict")
    print(f"  {'-'*42} {'-'*5} {'-'*8} {'-'*9} {'-'*5} {'-'*6} {'-'*4} {'-'*5} {'-'*6} {'-'*6}  -------")

    overall_match = 0.0      # length-weighted
    overall_total = 0.0
    overall_match_n = 0      # count-weighted (for comparison)
    overall_total_n = 0
    drifts: list[tuple[str, int, int, int]] = []  # label, expected, mode, n

    # per-source scorecards — both count- and length-weighted
    src_count: dict[str, list[bool]] = defaultdict(list)
    src_length_hit: dict[str, float] = defaultdict(float)
    src_length_tot: dict[str, float] = defaultdict(float)

    for rule in rules:
        expected = rule.get("maxspeed_kmh")
        tol = rule["tolerance_kmh"]
        hits = []
        for f, a in zip(feats, areas):
            if matches_rule(f["properties"], rule):
                hits.append((f["properties"], a))

        if not hits:
            print(f"  {rule.get('label', '?'):<42} {'0':>5}  (no matches)")
            continue

        speeds = [h[0]["maxspeed_kmh"] for h in hits]
        weights = [h[1] for h in hits]
        total_area = sum(weights) or 1.0
        total_length_km = total_area / 12.0 / 1000.0  # ~12 m avg road width

        mode = Counter(speeds).most_common(1)[0][0]
        # length-weighted mean
        wmean = sum(s * w for s, w in zip(speeds, weights)) / total_area

        within_n = sum(1 for s in speeds if abs(s - expected) <= tol)
        within_a = sum(w for s, w in zip(speeds, weights)
                       if abs(s - expected) <= tol)
        pct_within_n = within_n * 100 / len(speeds)
        pct_within_a = within_a * 100 / total_area

        overall_match += within_a
        overall_total += total_area
        overall_match_n += within_n
        overall_total_n += len(speeds)

        diff = abs(mode - expected)
        verdict = "OK" if diff <= tol else "DRIFT"
        if verdict == "DRIFT":
            drifts.append((rule.get("label", "?"), expected, mode, len(hits)))

        for (p, w) in hits:
            fam = _source_family(p["speed_source"])
            ok = abs(p["maxspeed_kmh"] - expected) <= tol
            src_count[fam].append(ok)
            src_length_tot[fam] += w
            if ok:
                src_length_hit[fam] += w

        print(f"  {rule.get('label', '?'):<42} {len(hits):>5} "
              f"{total_length_km:>8.1f} {expected:>9} "
              f"{mode:>5} {wmean:>6.0f} {diff:>4} {tol:>5} "
              f"{pct_within_n:>5.0f}% {pct_within_a:>5.0f}%  {verdict}")

    print()
    print(f"Overall count-weighted:  {overall_match_n}/{overall_total_n} "
          f"({overall_match_n*100/max(1, overall_total_n):.1f}%)")
    print(f"Overall length-weighted: "
          f"{overall_match*100/max(1, overall_total):.1f}%  "
          f"(by polygon area — long main-carriageway pieces dominate)")
    print(f"DRIFT rules: {len(drifts)}")
    for label, exp, mode, n in drifts:
        print(f"  - {label}: mode={mode} vs expected={exp} (n={n})")

    # ---- per-highway-class drift (for tuning SPEED_DEFAULT_KMH) -----------
    # For every feature whose speed came from class inference, compare the
    # inferred default against the nearest matching ground-truth rule and
    # report per-class signed drift so we know whether the default needs
    # to move up or down.
    class_drift: dict[str, list[int]] = defaultdict(list)
    for f, a in zip(feats, areas):
        p = f["properties"]
        if not p["speed_source"].startswith("inferred:highway_class"):
            continue
        # find any rule that matches this feature
        for rule in rules:
            if matches_rule(p, rule):
                class_drift[p["highway"]].append(
                    p["maxspeed_kmh"] - rule["maxspeed_kmh"])
                break
    if class_drift:
        print("\nPer-class inferred-default drift (inferred − ground truth):")
        print(f"  {'class':<20} {'n':>6} {'mean Δ':>7} {'median Δ':>9} "
              f"{'direction':>12}")
        for cls in sorted(class_drift, key=lambda c: -abs(
                statistics.mean(class_drift[c]))):
            deltas = class_drift[cls]
            m = statistics.mean(deltas)
            med = statistics.median(deltas)
            direction = ("↑ raise default" if m < -5 else
                         "↓ lower default" if m > 5 else
                         "ok")
            print(f"  {cls:<20} {len(deltas):>6} {m:>+7.1f} {med:>+9.1f} "
                  f"{direction:>12}")

    # ---- per-source accuracy ----------------------------------------------
    print("\nPer-source accuracy against ground truth:")
    print(f"  {'source':<28} {'n':>6} {'n-acc':>7} {'length(km)':>11} "
          f"{'L-acc':>7}")
    for src, results in sorted(src_count.items(), key=lambda kv: -len(kv[1])):
        n = len(results)
        w = sum(results)
        length_km = src_length_tot[src] / 12.0 / 1000.0
        length_acc = (src_length_hit[src] / src_length_tot[src] * 100
                      if src_length_tot[src] else 0.0)
        print(f"  {src:<28} {n:>6} {w*100/n:>6.1f}% "
              f"{length_km:>11.1f} {length_acc:>6.1f}%")

    # ---- global stats -----------------------------------------------------
    overall_source = Counter(f["properties"]["speed_source"] for f in feats)
    print(f"\nTop speed sources (all {len(feats):,} features):")
    for k, v in overall_source.most_common(8):
        print(f"  {k:<40} {v:>7}  ({v*100/len(feats):.1f}%)")

    warns = Counter()
    for f in feats:
        w = f["properties"].get("speed_warning")
        if w:
            warns[w.split(":", 1)[0]] += 1
    if warns:
        print(f"\nSpeed warnings ({sum(warns.values())} total):")
        for k, v in warns.most_common():
            print(f"  {k:<30} {v}")

    conf_buckets = Counter()
    for f in feats:
        c = f["properties"].get("speed_confidence", 0)
        bucket = ("high (>=0.9)" if c >= 0.9 else
                  "medium (0.6-0.9)" if c >= 0.6 else
                  "low (0.4-0.6)" if c >= 0.4 else
                  "very low (<0.4)")
        conf_buckets[bucket] += 1
    total = len(feats)
    print(f"\nConfidence buckets:")
    for k in ("high (>=0.9)", "medium (0.6-0.9)", "low (0.4-0.6)",
              "very low (<0.4)"):
        v = conf_buckets[k]
        print(f"  {k:<20} {v:>7} ({v * 100 / total:.1f}%)")


if __name__ == "__main__":
    main()
