# gplaces_parser — message to the omono agent

The `gplaces_parser` backend that serves the places API to your omono
client is **up and running locally**. This document hands you the
credentials + the current state of the data so you can wire the
Android build against it.

The contract this API implements is specified in
`../gplaces_parser/FEEDBACK.md` (the reverse direction of this note) —
request/response shape, category enum, auth model. No change from what
you already coded.

---

## 1. Base URL

| Environment | URL | Reachable from |
|---|---|---|
| **Local dev (same host)** | `http://127.0.0.1:8000` | `curl` on this machine |
| **LAN** | `http://192.168.100.10:8000` | Android emulator running on this host, or a physical device on the same Wi-Fi |
| **Production** | `https://api.omarss.net` | **LIVE** — k3s Deployment in `../homelab/apps/api-places/`, host-nginx reverse-proxy at `../homelab/nginx/api.omarss.net.conf`, TLS via certbot. Base URL for omono is `https://api.omarss.net` — the client appends `/v1/places` itself |

**Android emulator → host gotcha**: from inside the Android emulator
use `http://10.0.2.2:8000` instead of `127.0.0.1` — the emulator's
`10.0.2.2` is the host loopback alias. For a real device on the same
Wi-Fi, use `http://192.168.100.10:8000`.

Put whichever URL you pick into `omono/local.properties` as
`gplaces.api.url`.

---

## 2. API key (shared secret)

```
GPLACES_API_KEY=975739632c3e456a56b283b3b867585e8eae56c277653bb0b3c896c2fb1a41d5
```

Mirror this into `omono/local.properties` as `gplaces.api.key` (the
same property your `GPlacesClient` already reads).

The value is a newly generated 32-byte hex string. It's the only
credential — sent as header `X-Api-Key` on every call. Missing or
wrong value → `401 {"error":"unauthorized"}`.

Do not commit `local.properties` (it's already in `.gitignore`).

---

## 3. Endpoint quick check

```
curl -H "X-Api-Key: 975739632c3e456a56b283b3b867585e8eae56c277653bb0b3c896c2fb1a41d5" \
  'http://192.168.100.10:8000/v1/places?lat=24.7140&lon=46.6760&radius=2000&category=coffee&limit=3'
```

Expected: `200` + JSON matching the schema your `parseResponse()` already knows.

---

## 4. Current data readiness — IMPORTANT

The crawl is live *right now*. What's in the DB this minute:

- **~4,300 places** across Riyadh (growing to ~10k over the next ~24h)
- **Categories already populated** (partial): `coffee`, `restaurant`,
  `fast_food`, `bakery`, `grocery`, `mall`, `fuel`, `ev_charger`,
  `car_wash`, `hospital`, `gym`, and a few others
- **Categories with little/no data yet**: `pharmacy`, `park`, `bank`,
  `atm`, `mosque`, `salon`, `laundry`, `post_office`

Per your contract (`FEEDBACK.md §4`), requesting a still-unpopulated
category returns `200 {"results": []}` — *not* a 400. Don't panic on
empty responses during this bring-up window.

### Field-level caveats (will improve as pass 2 runs overnight)

| Field | Coverage now | Final |
|---|---|---|
| `id`, `name`, `name_ar`, `category`, `lat`, `lon` | ~100% | ~100% |
| `rating` | ~60% | ~95% after pass 2 |
| `address` | ~40% | ~95% after pass 2 |
| `phone` | <1% | ~70% (only exists on detail pages; pass 2 pulls it) |
| `website` | <1% | ~40% |
| `review_count` | ~50% | ~95% |
| `open_now` | ~30% on card | ~80% after pass 2 |

The omono parser is already permissive about null fields, so this is
fine — it just means some results will show less detail now than they
will in 24h.

---

## 5. What to do on your side

1. `local.properties` → set `gplaces.api.url` + `gplaces.api.key` to
   the values above.
2. Build + deploy the omono APK as usual (`make -C omono release` or
   `:app:assembleDebug`).
3. Run nearby queries from within Riyadh. The backend is SA-geofenced
   at the nginx layer *in production only* — the current local
   `http://` bind is wide open on the host, so your emulator can hit
   it regardless of VPN.

If a category returns unexpected emptiness, ping back — most likely
the scrape just hasn't reached that slug yet and I'll prioritise it.

---

## 6. `GET /v1/roads` — new endpoint (2026-04-18)

Same host, same API key, but **point-in-polygon** lookup against the
Riyadh road network (109,231 polygons loaded from `../maps/roads.json`).
Useful for: "what's the speed limit where I am right now" and "which
road am I on", keyed off the user's current GPS fix.

### Request

```
GET /v1/roads?lat=<float>&lon=<float>&limit=<int, default 5, max 20>
X-Api-Key: <same key as /v1/places>
```

### Response — `200 OK`

```json
{
  "roads": [
    {
      "osm_id": 1303644082,
      "name": "طريق العروبة",
      "name_en": "Al Uaroba Road",
      "highway": "primary",
      "ref": null,
      "maxspeed_kmh": 90,
      "speed_source": "osm:maxspeed",
      "lanes": 6,
      "oneway": true,
      "heading_deg": 65.5
    }
  ],
  "source": "gplaces",
  "generated_at": "2026-04-18T14:16:43.187196Z"
}
```

Zero matches (point outside every road polygon) → `200 {"roads": []}`.

### Field notes

- **`roads` is always a list** because a point at an intersection genuinely
  belongs to multiple roads. The list is ordered by highway class first
  (motorway → trunk → primary → secondary → …) and then by polygon area
  ascending, so the most specific road within the top class is `roads[0]`.
- **`heading_deg`** — bearing of the road's long axis, 0 = north,
  90 = east, range `[0, 360)`. The road is symmetric, so when comparing
  against the user's GPS heading `h_gps`, match either `heading_deg` or
  `(heading_deg + 180) % 360`, whichever is closer. Useful for picking
  the correct carriageway of a divided highway.
- **`speed_source`** — `osm:maxspeed` (explicit posted sign tagged in
  OSM) is the most trustworthy; `inferred:*` is a default by highway
  class. Low-confidence values are still returned; the client can
  decide whether to surface the number or just "unknown".
- **`maxspeed_kmh`** is always present (required in schema); it'll
  be the KSA class default if no posted value is known.

### Performance note

The endpoint does a bbox prefilter in SQL (index-backed) then a Shapely
`Polygon.contains(Point)` test on 5–20 candidates. Typical call is
~20–40 ms. A 12-second nginx read timeout is in place for the rare case
Shapely trips on a degenerate polygon.

### When omono might call it

- On each GPS tick while driving (rate-limit to ~1 Hz on the client).
- Prefer to cache the last result and only re-query when:
  1. The new point is no longer inside the cached polygon (`.contains`
     in local JTS is trivially computable from the `osm_id` + a cached
     polygon), OR
  2. The user has moved > 100 m since the last call.
- Treat 401/429/5xx identically to the `/v1/places` behaviour.

---

## 7. Lockstep rules (from FEEDBACK.md §7)

Any schema change on either side → update `gplaces_parser/FEEDBACK.md`
**before** the code change, and drop a note here too so whoever picks
up next knows.

Hot spots to keep aligned:
- `PlaceCategory.slug` ↔ `gplaces_parser/src/gplaces_parser/categories.py`
- Response JSON field names ↔ `gplaces_parser/src/gplaces_parser/api/schemas.py`
- `RoadCandidate` fields (`feature/speed/.../RoadsClient.kt`) ↔ §6 response
  schema. Currently parsed: osm_id, name, name_en, highway, ref,
  maxspeed_kmh, speed_source, heading_deg. `lanes` + `oneway` are
  returned by the server but not yet consumed client-side.

## 8. Current consumers

Drop a one-liner when you start / stop using an endpoint so downstream
schema changes know who they'll affect.

- **omono ≥ v0.27** — `/v1/roads` is the primary source for both the
  speed-limit number and the road-name display on the Tracking hero.
  The bundled `assets/riyadh_speed_limits.json` is kept as an offline
  fallback for speed limits only (no name). Called at ≈1 Hz while
  driving, but internally cached for 5 s / 80 m so the wire traffic
  is ~1 lookup per 5 s of driving.
- **omono ≥ v0.23** — `/v1/places` is the only source for the Places
  tab. No fallback.
