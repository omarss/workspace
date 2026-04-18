#!/usr/bin/env bash
# Fetches every OSM node / way tagged amenity=place_of_worship AND
# religion=muslim inside greater Riyadh, producing a compact JSON the
# MosqueDirectory consumes offline. Same pattern as fetch-speed-limits.sh.
#
# The backend /v1/places?category=mosque is still sparse at time of
# writing; even if it catches up later the offline asset is a good
# fallback for when the user drives with the internet-kill-switch on.
#
# Usage: ./scripts/fetch-mosques.sh
#
# Deps: curl, python3.

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="app/src/main/assets/riyadh_mosques.json"
mkdir -p "$(dirname "$OUT")"

# Same bbox as fetch-speed-limits.sh so the two datasets stay aligned.
BBOX="24.30,46.20,25.30,47.30"

# Match both nodes and ways. Closed ways for large mosques, nodes for
# small neighbourhood ones. `out center` collapses way geometries to
# a single lat/lon so the client only ever sees a point.
QUERY=$(cat <<EOF
[out:json][timeout:120];
(
  node["amenity"="place_of_worship"]["religion"="muslim"](${BBOX});
  way["amenity"="place_of_worship"]["religion"="muslim"](${BBOX});
);
out center tags;
EOF
)

TMP=$(mktemp)
trap 'rm -f $TMP' EXIT

echo "==> Querying Overpass for Riyadh mosques"
curl -s -X POST 'https://overpass-api.de/api/interpreter' \
    --data-urlencode "data=${QUERY}" \
    -o "$TMP"

SIZE=$(stat -c%s "$TMP")
echo "    raw Overpass response: ${SIZE} bytes"

echo "==> Compacting"
python3 - "$TMP" "$OUT" "$BBOX" <<'PY'
import json, sys

raw_path, out_path, bbox_str = sys.argv[1], sys.argv[2], sys.argv[3]
bbox = [float(x) for x in bbox_str.split(',')]

with open(raw_path) as f:
    data = json.load(f)

# Short-key output schema — mirrors riyadh_speed_limits.json style.
#   n  = display name (str, optional — many local mosques are untagged)
#   lat, lon = rounded to 5 decimals (~1 m precision)
out = []
for el in data.get('elements', []):
    if el.get('type') == 'node':
        lat, lon = el.get('lat'), el.get('lon')
    else:
        c = el.get('center') or {}
        lat, lon = c.get('lat'), c.get('lon')
    if lat is None or lon is None:
        continue
    tags = el.get('tags') or {}
    # Prefer English name when OSM supplies it; otherwise fall back
    # to the primary name tag (often Arabic) or nothing.
    name = (tags.get('name:en')
            or tags.get('name')
            or tags.get('int_name')
            or '').strip() or None
    out.append({
        'lat': round(lat, 5),
        'lon': round(lon, 5),
        'n': name,
    })

# Stable sort for diff-friendliness.
out.sort(key=lambda m: (m['lat'], m['lon']))

payload = {
    'bbox': bbox,
    'source': 'OpenStreetMap (Overpass API)',
    'mosques': out,
}

with open(out_path, 'w') as f:
    json.dump(payload, f, separators=(',', ':'), ensure_ascii=False)

print(f'    mosques kept: {len(out)}')
print(f'    asset:        {out_path}')
PY

FINAL=$(stat -c%s "$OUT")
echo "==> Wrote ${FINAL} bytes to ${OUT}"
echo "    Commit the change to ship in the next release."
