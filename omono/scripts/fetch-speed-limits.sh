#!/usr/bin/env bash
# Fetches every OSM way with a maxspeed tag inside greater Riyadh and
# packs it into the compact JSON the LocalSpeedLimitSource consumes.
# Output is committed to the repo so the app ships with offline speed
# limits — no runtime Overpass calls.
#
# Re-run occasionally to pick up community-contributed tags. Each run
# overwrites the asset; diff it before committing to sanity-check.
#
# Usage: ./scripts/fetch-speed-limits.sh
#
# Deps: curl, python3.

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="app/src/main/assets/riyadh_speed_limits.json"
mkdir -p "$(dirname "$OUT")"

# Greater Riyadh — wide enough to include airport, Diriyah, and the
# ring-road approach from Mecca Rd. Adjust bbox if the user drives
# outside this box regularly. OSM ways that cross the boundary are
# included as long as at least one node is inside.
#
# Order: south_lat, west_lon, north_lat, east_lon.
BBOX="24.30,46.20,25.30,47.30"

QUERY="[out:json][timeout:120]; way(${BBOX})[highway][maxspeed]; out tags geom;"

TMP=$(mktemp)
trap 'rm -f $TMP' EXIT

echo "==> Querying Overpass for Riyadh speed limits"
curl -s -X POST 'https://overpass-api.de/api/interpreter' \
    --data-urlencode "data=${QUERY}" \
    -o "$TMP"

SIZE=$(stat -c%s "$TMP")
echo "    raw Overpass response: ${SIZE} bytes"

echo "==> Compacting"
python3 - "$TMP" "$OUT" "$BBOX" <<'PY'
import json, re, sys

raw_path, out_path, bbox_str = sys.argv[1], sys.argv[2], sys.argv[3]
bbox = [float(x) for x in bbox_str.split(',')]

with open(raw_path) as f:
    data = json.load(f)

# Short-key output schema — the Android side reads the same keys.
#   l  = maxspeed in km/h (float, 1 decimal)
#   g  = flat [lat, lon, lat, lon, ...] array, lat/lon rounded to 5
#        decimals (~1 m precision, the noise floor of consumer GPS)
ways_out = []
re_num = re.compile(r'^(\d+(?:\.\d+)?)\s*(mph)?', re.IGNORECASE)
for el in data.get('elements', []):
    tags = el.get('tags', {})
    raw_ms = tags.get('maxspeed', '').strip()
    if not raw_ms:
        continue
    m = re_num.match(raw_ms)
    if not m:
        continue
    kmh = float(m.group(1))
    if kmh <= 0:
        continue
    if m.group(2):  # mph suffix
        kmh *= 1.609344
    geom = el.get('geometry') or []
    if len(geom) < 2:
        continue
    pts = []
    for p in geom:
        pts.append(round(p['lat'], 5))
        pts.append(round(p['lon'], 5))
    ways_out.append({'l': round(kmh, 1), 'g': pts})

# Sort ways for deterministic diff-friendliness across runs.
ways_out.sort(key=lambda w: (w['g'][0], w['g'][1], w['l']))

output = {
    'bbox': bbox,
    'source': 'OpenStreetMap (Overpass API)',
    'ways': ways_out,
}

with open(out_path, 'w') as f:
    json.dump(output, f, separators=(',', ':'))

print(f'    ways kept: {len(ways_out)}')
print(f'    asset:     {out_path} ({sum(1 for _ in open(out_path))} lines)')
PY

FINAL=$(stat -c%s "$OUT")
echo "==> Wrote ${FINAL} bytes to ${OUT}"
echo "    Commit the change to ship in the next release."
