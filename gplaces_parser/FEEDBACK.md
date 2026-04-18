# gplaces_parser — API contract expected by omono

This document is the concrete requirement list from the **omono Android
client** (`workspace_personal/omono`) — the side that will consume this
service over HTTP. It exists so whoever builds the FastAPI layer knows
exactly what to ship.

The omono side of the integration has already been implemented against
this contract (`feature/places/.../GPlacesClient.kt`). Any deviation on
the server side will need a matching change on the client, so please
confirm with the user before varying these shapes.

---

## 1. Deployment target

- **Host**: k8s on the same machine (`homelab/apps/...`). Match the
  existing `apps-host` pattern — HTTP-only Deployment + Service, nginx
  vhost without the `listen 443 ssl` block (certbot adds TLS after the
  fact via `sudo certbot --nginx -d api.omarss.net`).
- **DNS / vhost name**: `api.omarss.net` (general personal API host —
  gplaces lives under `/v1/places` there).
- **Port inside the pod**: `8000` (conventional FastAPI default; any
  port is fine, the Service maps to it).
- **Geofence**: already covered by the Saudi geofence at the host level.
  Nothing to do in the app.
- **Resource limits**: the scrape lives in Postgres; API-tier is pure
  read. 128 Mi / 250 m CPU per replica is plenty. Horizontal scale = 1.

### Postgres access from the pod

The Postgres instance is on the host at `localhost:5432`. Easiest path
from inside the cluster is to resolve the host via `host.minikube.internal`
/ the node's gateway IP. Expose via `DATABASE_URL` env var.

---

## 2. Authentication

- **Header**: `X-Api-Key: <secret>`. No cookies, no OAuth, no bearer
  token. The secret is static and lives in a k8s `Secret`.
- The FastAPI app reads it from `GPLACES_API_KEY` env var on startup
  and compares with constant-time string equality on every request.
- Missing or wrong key → `401 Unauthorized` with body
  `{"error": "unauthorized"}`. No body shape beyond that — do not leak
  whether the key was missing vs. wrong.
- The client sends the header on every request. No session, no refresh.

Generate the secret once (`openssl rand -hex 32`), put it in the k8s
secret, mirror it into omono's `local.properties` as `gplaces.api.key`.

---

## 3. Primary endpoint — `GET /v1/places`

This is the only endpoint omono calls. Everything else (`/v1/place/{id}`,
`/v1/reviews`, etc.) is optional — build them if it suits the data
model but omono doesn't depend on them.

### Query parameters

| Name       | Type    | Required | Default | Notes |
|------------|---------|----------|---------|-------|
| `lat`      | float   | yes      | —       | WGS84, Riyadh range: 24.5–25.1 |
| `lon`      | float   | yes      | —       | WGS84, Riyadh range: 46.4–47.1 |
| `radius`   | int     | yes      | —       | Metres. Omono sends 1000, 5000, 20000 |
| `category` | string  | yes      | —       | Slug from the enum below (case-insensitive) |
| `limit`    | int     | no       | 25      | Hard cap at 50 |
| `lang`     | string  | no       | `en`    | `en` or `ar` — returns localised names when both exist |

### Response — `200 OK`

```json
{
  "results": [
    {
      "id": "ChIJ...place_id...",
      "name": "Row Cafe",
      "name_ar": "مقهى رو",
      "category": "coffee",
      "lat": 24.7136,
      "lon": 46.6753,
      "address": "King Fahd Rd, Riyadh",
      "phone": "+966500000000",
      "rating": 4.6,
      "review_count": 1832,
      "open_now": true,
      "website": "https://..."
    }
  ],
  "source": "gplaces",
  "generated_at": "2026-04-17T14:58:10Z"
}
```

Required per result: `id`, `name`, `category`, `lat`, `lon`. Everything
else is optional — the omono parser tolerates null / missing fields
and hides whatever isn't available.

Results must be **sorted by distance ascending** from the query point.
The client relies on that ordering for its "closest first" rendering
and does not re-sort.

### Response — `400 Bad Request`

Any parameter-level failure. Body: `{"error": "string explaining why"}`.
The client will show the string to the user if present.

### Response — `401 Unauthorized`

See authentication section.

### Response — `429 Too Many Requests`

If you add rate limiting, use this code with a `Retry-After` header
(seconds). The client treats 429 as an expected transient error and
backs off — no crash.

### Response — `5xx`

Anything else the client treats as "source unavailable" and surfaces a
generic error. Prefer returning empty `results` with 200 over 5xx when
the underlying data is simply absent (e.g., no POIs in the cell).

---

## 4. Category slug enum

omono's `PlaceCategory` has the 19 values below. The API must accept
every slug and map it to the Arabic query categories the scraper
collected. Unknown slugs → `400`.

| Slug          | Meaning                  | Hint for mapping |
|---------------|--------------------------|------------------|
| `coffee`      | Coffee shops             | `مقاهي` |
| `restaurant`  | Restaurants (any cuisine)| `مطاعم` |
| `fast_food`   | Fast food                | `وجبات سريعة` |
| `bakery`      | Bakery / patisserie      | `مخبز` |
| `grocery`     | Supermarkets + grocery   | `سوبر ماركت` |
| `mall`        | Shopping malls           | `مول` |
| `fuel`        | Petrol / gas stations    | `محطة وقود` |
| `ev_charger`  | EV charging stations     | `شاحن سيارة كهربائية` |
| `car_wash`    | Car wash                 | `غسيل سيارات` |
| `pharmacy`    | Pharmacies               | `صيدلية` |
| `hospital`    | Hospitals                | `مستشفى` |
| `gym`         | Gyms / fitness           | `نادي رياضي` |
| `park`        | Parks                    | `حديقة` |
| `bank`        | Banks                    | `بنك` |
| `atm`         | ATMs                     | `صراف آلي` |
| `mosque`      | Mosques                  | `مسجد` |
| `salon`       | Barber / hair salon      | `حلاق` |
| `laundry`     | Laundry / dry cleaner    | `مغسلة` |
| `post_office` | Post offices             | `مكتب بريد` |

If some slugs don't have scraped data yet, return an empty `results`
array with `200 OK`, not `400`. Log the gap server-side so we know what
to backfill.

---

## 5. Rate + caching expectations from the client

- Omono hits `/v1/places` once per user-triggered refresh
  (screen-open, pull-to-refresh, category change, radius change).
- No polling, no background calls. Peak realistic usage: ~10 rpm from
  a single user.
- Expect `If-None-Match` / `ETag` support on future iterations — not
  required for v1. A naive server is fine.
- A cache layer on the server (1-hour TTL by cell+category) would be
  plenty; Google places data doesn't move.

---

## 6. Non-requirements (explicit)

- **No POST / PUT / DELETE** endpoints needed.
- **No account model** — single static API key is fine for this
  personal use.
- **No pagination** in v1 — `limit` up to 50 covers every screen.
- **No reviews** endpoint needed by omono. You can still build it; the
  client just won't call it.

---

## 7. Coordination back to omono

If any of the above needs to change — field names, query shape, auth
model — please drop a note back here (or an issue on the workspace
repo) so the omono client can be updated in lockstep. Silent drift is
the main failure mode, and the client doesn't have retries or schema
version negotiation.

The omono-side contract lives in:

- `omono/feature/places/src/main/kotlin/net/omarss/omono/feature/places/GPlacesClient.kt` — HTTP + parser
- `omono/feature/places/src/test/kotlin/net/omarss/omono/feature/places/GPlacesClientTest.kt` — parser tests doubling as response-shape examples
- `omono/feature/places/src/main/kotlin/net/omarss/omono/feature/places/Place.kt` — the domain model we deserialise into

---

## 8. 2026-04-18 — asks raised by omono, verification of status

omono/FEEDBACK.md §9 asked for five backend changes. The doc on the
omono side was updated acknowledging them, but a live curl probe of
`https://api.omarss.net` on **2026-04-18 15:36 UTC** shows none of them
are actually implemented on the server yet. Evidence below; please
land each change **and re-probe with curl** before marking done so we
don't loop on "said addressed, still broken".

Key used: the same `X-Api-Key` the omono client is pinned to.

### 8.1 `category=all` / comma-list — NOT IMPLEMENTED

```
$ curl -H "X-Api-Key: ..." \
    'https://api.omarss.net/v1/places?lat=24.7136&lon=46.6753&radius=2000&category=all&limit=5'
{"error":"unknown category: all"}                            # HTTP 400

$ curl ... '.../v1/places?...&category=coffee,restaurant&limit=5'
{"error":"unknown category: coffee,restaurant"}              # HTTP 400
```

Expected: `200` with a union, deduped by `id`, as specced in
`omono/FEEDBACK.md §9.1`. This one is a ship-blocker — omono currently
fans out 19 parallel GETs (one per `PlaceCategory`) to build its
default "All" view, which is wasteful on both sides.

### 8.2 `min_rating` + `min_reviews` — ACCEPTED BUT IGNORED

Server doesn't reject the params (no 400), but the response body is
identical with or without them:

```
$ curl ... '.../v1/places?lat=24.7136&lon=46.6753&radius=2000&category=restaurant&limit=20'
# 20 results, first five are rating=3.2/reviews=6, rating=None,
# rating=None, rating=None, rating=1.0/reviews=1

$ curl ... '.../v1/places?...&category=restaurant&min_rating=4&min_reviews=100&limit=20'
# same 20 results in the same order, same unrated / low-rated entries
```

Expected: drop everything with `rating < min_rating` OR
`review_count < min_reviews` (and drop null-rated / null-reviewed
places when either threshold is > 0). See §9.2 of the omono doc.

### 8.3 `cid` field in response — NOT ADDED

Current single-result shape:

```json
{
  "id": "0x3e2f0306b560991b:0x72677b2c41fb4f9c",
  "name": "C SQUARE Speciality Cafe",
  ...
  // no "cid" key
}
```

Expected: add `cid` (decimal string, since u64 overflows JSON number)
sibling to `id`. The client needs it for the Google Maps deep link
(`maps.google.com/?cid=<n>`). Parsing works today but fails on edge
cases — see `parseCidFromFtid` in the omono `PlacesScreen.kt`.

### 8.4 Text search (`q` param or `/v1/places/search`) — NOT IMPLEMENTED

```
$ curl ... '.../v1/places?lat=...&lon=...&radius=5000&q=starbucks&limit=5'
{"error":"category: Field required"}                         # HTTP 400

$ curl ... '.../v1/places/search?lat=...&q=starbucks&limit=5'
{"error":"Not Found"}                                        # HTTP 404
```

Expected: either `q=<str>` on `/v1/places` (category optional when `q`
is present, fuzzy-match on `name`+`address`) OR a new
`/v1/places/search` with the same response shape.

### 8.5 `snap_m` on `/v1/roads` — ACCEPTED BUT IGNORED

Off-polygon point, no `snap_m`:

```
$ curl ... '.../v1/roads?lat=24.80000&lon=46.60000'
{"roads":[],"source":"gplaces","generated_at":"..."}
```

Same point with `snap_m=200`:

```
$ curl ... '.../v1/roads?lat=24.80000&lon=46.60000&snap_m=200'
{"roads":[],"source":"gplaces","generated_at":"..."}
```

Expected: when `snap_m > 0` and no polygon contains the point, return
the nearest road whose polygon is within `snap_m` metres, with
`snapped: true` and `snap_distance_m: <float>` on the result.

### Verification protocol going forward

When a change lands, please run the exact curl from §9 of
`omono/FEEDBACK.md` (or the sections here) and paste the output as
evidence of implementation. That way we don't need a second round
of confirmation.
