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

---

## 9. Backend asks from omono (ordered by impact)

These would let omono drop client-side workarounds. Items marked
**ship-blocker** affect a feature currently in production; the rest
are quality-of-life.

> **Status roundup (2026-04-18, pending deploy)** — 9.1 / 9.2 / 9.3 /
> 9.4 / 9.5 are all **SHIPPED on main**. They go live after
> `make deploy` + certbot. Call out any contract mismatch ASAP.

### 9.1 `/v1/places` — "all categories" mode  *(ship-blocker)*

**Status:** ✅ shipped. `category=all` disables the filter; a
comma-separated list (`category=coffee,bakery,fast_food`) unions
slugs server-side. Unknown slugs in the list → `400`. Single-slug
back-compat unchanged.

**Why:** The Places tab's default view is now "All", not a single
category. To build that list omono fans out **19 parallel GET calls**,
one per `PlaceCategory`, and merges the responses. That's bad on three
axes: wasted RPS on the backend, burns the user's data plan
(especially while the internet-kill-switch is about to disable the
connection mid-drive), and the first open is ~500 ms of waterfall
latency per category at best.

**Ask:** Accept `category` as either a comma-separated list or a
special value:

```
GET /v1/places?lat=...&lon=...&radius=5000&category=all&limit=50
GET /v1/places?lat=...&lon=...&radius=5000&category=coffee,restaurant,bakery&limit=50
```

- `category=all` returns everything within `radius` (already deduped
  server-side by `id`), capped at `limit`.
- Comma-separated picks a specific union.
- Current single-category behaviour must keep working unchanged.

Response JSON shape stays the same — `results: [...]` — so the Kotlin
parser is a no-op change. Add a field per result (already kind-of
present via `category`) so mixed-category responses still carry the
per-place category.

### 9.2 `/v1/places` — server-side quality filter

**Status:** ✅ shipped. `min_rating=<float, 0..5>` and
`min_reviews=<int>` query params; both default to `0` = no filter.
Applied *before* `limit`, so threshold-dropped rows don't empty the
page. Rows missing `rating` or `reviews_count` are dropped when
either threshold is > 0, matching the client-side behaviour.

**Why (original ask):** omono's default view hides places with `rating < 4` OR
`review_count < 100`. Today that gate runs client-side, so the backend
still ships the noise and the client discards it. On the all-category
view this can be 70 %+ of the payload.

**Ask:** Two optional numeric query params, applied server-side
*before* the `limit` cap so the list doesn't get emptied by the gate:

```
GET /v1/places?...&min_rating=4&min_reviews=100
```

Defaults: `0` (no filter), i.e. current behaviour when the params are
omitted. Places missing either field (the backend has no rating or
review_count at all for some entries) should be **dropped** when
either threshold is > 0 — matching omono's current client-side logic.

### 9.3 `/v1/places` — canonical CID in response

**Status:** ✅ shipped. Each result now carries a sibling `cid`
field — decimal string extracted from the second hex chunk of `id`.
Null when `id` is malformed (never expected for real Google CIDs).
`id` is unchanged.

**Why (original ask):** The current `id` shape `"0x<fid_hex>:0x<cid_hex>"` works, but
it forces the client to parse it before building the
`https://www.google.com/maps?cid=<n>` deep link that lands the user
on a place's review page. Two places have already broken parsing once
in testing (length > 16 chars, leading zeros). See `parseCidFromFtid`
in `omono/app/src/main/kotlin/net/omarss/omono/ui/places/PlacesScreen.kt`.

**Ask:** Add a sibling field carrying the decimal CID directly:

```json
{
  "id": "0x3e2f03001ea03a6f:0x555a69b1d55e7a4b",   // unchanged
  "cid": "6149989055815169611",                     // NEW — decimal string
  ...
}
```

String (not int) because `u64` overflows `i64` / JS `number`.

### 9.4 `/v1/places` — text search

**Status:** ✅ shipped as a dedicated endpoint — `GET /v1/search`.
Same auth header, same response-ish shape (adds a `score` field).
Supports Arabic + English, typos (pg_trgm fuzzy), optional
`category` filter, optional `lat`+`lon`+`radius` geographic prefilter.

```
GET /v1/search?q=<text>&category=<optional>&lat=<opt>&lon=<opt>&radius=<opt>&limit=<default 20, max 50>&lang=ar|en
X-Api-Key: <same key>
```

Response:
```json
{
  "results": [
    {
      "id": "0x3e2f…:0x8a7b…",
      "name": "Starbucks",
      "name_ar": "ستاربكس",
      "category": "coffee",
      "lat": …, "lon": …,
      "score": 2.574,
      "...": "same optional fields as /v1/places"
    }
  ],
  "query": "starbucks",
  "source": "gplaces",
  "generated_at": "..."
}
```

Ranking: `ts_rank(fts) * 2 + max(trigram_ar, trigram_en)`. Higher
score is better. Ties break on `review_count`.

**Why (original ask):** The new search field in omono filters the already-fetched
list by substring. Works, but limited to whatever the backend chose
to return for the given category/radius. A user searching for
"Urth Caffe" that isn't among the top 50 returned results won't find
it even if it's two blocks away.

**Ask:** Either:
- Accept a `q=<str>` param on `/v1/places` that fuzzy-matches on
  `name` + `address` server-side, OR
- Add a dedicated `/v1/places/search?q=<str>&lat=...&lon=...&radius=...`
  that returns the same JSON shape.

Lower priority than 9.1–9.3; the client-side filter is acceptable for
now.

### 9.8 Arabic-aware search — normalisation + synonyms (2026-04-18)

**Status:** ✅ shipped (pending `make deploy`). Applies to both
`/v1/search` and `/v1/reviews/search` with no API change — just
smarter matching:

- **Normalization (SQL `ar_normalize`):**
  - strips harakat, tatweel (U+0640), and superscript alef
  - folds Alef variants `أ إ آ ٱ` → `ا`
  - folds alef-maqsura `ى` → `ي`
  - folds ta-marbuta `ة` → `ه` (so colloquial `قهوه` matches formal `قهوة`)
- **Synonyms (app layer):** query tokens that appear in a known group
  OR-expand to every member of the group before `to_tsquery`. Groups
  currently defined for coffee, restaurant, fast food, bakery,
  grocery, mall, fuel, EV charger, car wash, pharmacy, hospital, gym,
  park, bank, ATM, mosque, salon, laundry, post office, library —
  each with both Arabic and English variants plus common transliterations.
- **Applies equally to reviews search.** `قهوه` finds English-text
  reviews that mention `coffee`; `مكتبة` finds reviews mentioning
  `books` or `library`.

No omono-side change. The existing `q=<text>` parameter just starts
returning better results.

### 9.7 `GET /v1/reviews/search` — keyword search in review bodies (2026-04-18)

**Status:** ✅ shipped (pending `make deploy`). Works over ~2k reviews
today, will grow as pass 2 drains in the background.

```
GET /v1/reviews/search?q=<text>&category=<opt>&place_id=<opt>&min_rating=<1..5>&limit=<default 20, max 50>&lang=ar|en
X-Api-Key: <same key>
```

Response:
```json
{
  "results": [
    {
      "review_id": "...",
      "rating": 5,
      "text": "...",
      "snippet": "Delicious <b>coffee</b>. Beautiful place...",
      "published_at": "2026-03-12T...",
      "author": "Bsmh A",
      "likes": 3,
      "place": {
        "id": "0x…:0x…",
        "name": "Joe Barrel Coffee",
        "name_ar": "جو برل",
        "category": "coffee",
        "lat": 24.72,
        "lon": 46.68,
        "rating": 4.5
      },
      "score": 0.0987
    }
  ],
  "query": "coffee",
  "source": "gplaces",
  "generated_at": "..."
}
```

- **`snippet`** wraps matched tokens in `<b>…</b>` (use directly in
  HTML; strip tags for plain-text rendering).
- **`category`** accepts the same `all` / comma-separated grammar as
  `/v1/places` (§9.1). Filters reviews whose *parent place* falls in
  those categories.
- **`place_id`** narrows to a single place's reviews.
- **`min_rating`** = only reviews whose star rating is `≥` this (1–5).
- Ranking: `ts_rank` descending, ties on `likes` then `published_at`.

Arabic + English both supported; the `simple` tsconfig tokenises on
whitespace + case-folds without stemming, which is what Arabic needs
(no stemmer shipped) and English tolerates.

### 9.6 New category — `library` (2026-04-18)

**Status:** ✅ added server-side. 120 new scrape jobs seeded (~2 h to
ingest; will trickle in alongside the main run). The slug covers **two
user intents conflated into one category**:

1. Pure public reading libraries (`مكتبة عامة` / `public library` queries).
2. Coffee shops that stock books / study-cafes (`كافيه مكتبة` / `book cafe`
   queries).

Dedup by place_id means hybrid places that show up under multiple
queries collapse to one row. Once ingested, calls like:

```
GET /v1/places?category=library&lat=…&lon=…&radius=5000
```

…return the union. To add `PlaceCategory.LIBRARY` on the omono side,
extend the enum + the slug mapping in `GPlacesClient.kt`.

**Known caveat:** Arabic retail bookstores (e.g. Jarir, `مكتبة جرير`)
often self-categorise as libraries on Google. Expect some noise until
reviews / hours / category-hint fields let us tighten.

### 9.5 `/v1/roads` — name fallback when polygon is missed

**Status:** ✅ shipped. Optional `snap_m=<int, 0..200>` query param.
`snap_m=0` (default) keeps current exact-contains behaviour. When > 0
and no polygon contains the point, the **nearest** road polygon
within `snap_m` metres is returned as a single-element list with:

```json
{"roads":[{..., "snapped": true, "snap_distance_m": 14.2, "heading_deg": 65.5}]}
```

Distance is computed in a local equirectangular projection so metres
are real (not degree-diagonals). Verified against Al Uroubah at a
+0.0005-degree offset: `snap_distance_m=14.2`, correct road.

**Why (original ask):** Tight road polygons mean a fix a few metres off the
centerline returns `roads: []` even on major streets. See the test
runs I captured against `24.7136,46.6753` (hit Al Uaroba) vs the
+0.0001 offset (empty). On real drives this surfaces as "road name
disappears" whenever the fix drifts. omono currently shows stale-last
name via its own cache, but a server-side nearest-road fallback
(e.g. snap within 20 m of any polygon edge) would feel much better.

**Ask:** Optional `snap_m=<int>` param, default `0` (current
exact-contains behaviour). When > 0 and no polygon contains the point,
return the closest road whose polygon is within `snap_m` metres, with
an added flag:

```json
{"roads":[{..., "snapped": true, "snap_distance_m": 14.3}]}
```

Client uses `snapped` to skip trusting the speed limit (display "~90
km/h" instead of "90 km/h") while still surfacing the road name.
