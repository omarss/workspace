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
