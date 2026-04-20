# gplaces_parser

Two halves of one personal product:

1. **Scraper** — a Playwright-driven Chromium that crawls Google Maps
   results for Arabic categories across ~30 Riyadh districts, captures
   places + reviews, and upserts everything into Postgres 18.
2. **API** — a FastAPI service exposing `/v1/*` endpoints that omono
   and other clients call. Deployed to k3s, reverse-proxied by host
   nginx at `https://api.omarss.net`.

The omono-side contract is in `FEEDBACK.md`; it has not changed.

---

## API reference

Base URL (production): `https://api.omarss.net`
Base URL (dev): `http://127.0.0.1:8000`

Auth: every request sends `X-Api-Key: <secret>`. Missing/wrong →
`401 {"error": "unauthorized"}`. The only other error body shape is
`{"error": "<string>"}` on `400`.

Every endpoint returns `200` with a stable JSON shape (see below).
Transient backend failures surface as `5xx`; the client should treat
them as "source unavailable" rather than user error.

### `GET /v1/places` — nearby by category

Nearest N places of a category within radius, sorted by distance ASC.

| Parameter | Type | Required | Default | Notes |
|---|---|---|---|---|
| `lat` | float | yes | — | WGS84 |
| `lon` | float | yes | — | WGS84 |
| `radius` | int | yes | — | Metres, 1..50000 |
| `category` | string | yes | — | Slug, `all`, or comma-separated list (see §Categories) |
| `limit` | int | no | 25 | Hard-capped at 50 per page |
| `offset` | int | no | 0 | Pagination offset, 0..10000 |
| `lang` | string | no | `en` | `en` or `ar` — selects which of `name` / `name_ar` is primary |
| `min_rating` | float | no | 0 | `0..5`; drops places with rating below or missing |
| `min_reviews` | int | no | 0 | Drops places with review_count below or missing |
| `include_closed` | bool | no | `false` | When `false`, filters out `CLOSED_TEMPORARILY` + `CLOSED_PERMANENTLY` |

Response:

```json
{
  "results": [
    {
      "id": "0x3e2f…:0x8a7b…",
      "cid": "12564589884192500290",
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
      "website": "https://…",
      "business_status": "OPERATIONAL"
    }
  ],
  "pagination": {"offset": 0, "limit": 25, "next_offset": 25, "has_more": true},
  "source": "gplaces",
  "generated_at": "2026-04-20T18:33:00Z"
}
```

- `id` is Google's hex CID (`0x<fid>:0x<cid>`). `cid` is the decimal
  form (string, u64-safe) for building `maps?cid=<n>` deep links.
- `business_status` ∈ `{OPERATIONAL, CLOSED_TEMPORARILY, CLOSED_PERMANENTLY, null}`.
- `open_now` is derived from the card's "Closes X" / "Opens X" hint;
  only reliable when present, never a substitute for real hours.

### `GET /v1/search` — keyword + fuzzy search across places

Ranks by exact/prefix/substring bonus, phrase adjacency, synonym-
expanded FTS, and trigram fuzzy — in that order.

| Parameter | Type | Required | Default | Notes |
|---|---|---|---|---|
| `q` | string | yes | — | Free text, Arabic or English, 1..100 chars |
| `category` | string | no | (all) | Single slug or comma-separated |
| `lat`/`lon`/`radius` | — | no | — | Optional bbox prefilter; all three or none |
| `limit` | int | no | 20 | 1..50 |
| `offset` | int | no | 0 | Pagination |
| `lang` | string | no | `en` | `en` or `ar` |
| `min_rating` / `min_reviews` / `include_closed` | — | no | — | Same semantics as `/v1/places` |

Response shape is the same as `/v1/places` + an extra `score` per
result + `query` at the top level. Score is relative to the query
(not a fixed scale); higher = better match.

Arabic handling applies normalisation (`أ إ آ ٱ` → `ا`, `ى` → `ي`,
`ة` → `ه`, strip harakat + tatweel) on both the index and the
query, plus synonym expansion across Arabic/English pairs (see
§Synonyms).

### `GET /v1/roads` — which road am I on + speed limit

Point-in-polygon over ~109 k Riyadh road polygons.

| Parameter | Type | Required | Default | Notes |
|---|---|---|---|---|
| `lat`/`lon` | float | yes | — | |
| `limit` | int | no | 5 | 1..20; multiple overlaps ordered by class + polygon area |
| `snap_m` | int | no | 0 | If `>0` and no polygon contains the point, returns the nearest road polygon within `snap_m` metres (`0..200`), marked `snapped=true` |

Response:

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
      "heading_deg": 65.5,
      "snapped": false,
      "snap_distance_m": 0
    }
  ],
  "source": "gplaces",
  "generated_at": "..."
}
```

- `heading_deg` is the bearing of the road's long axis (`0..360`, `0=N`);
  road is symmetric so clients compare a GPS heading to both
  `heading_deg` and `(heading_deg + 180) % 360`.
- `snap_distance_m` > 0 signals the GPS fix was just outside the polygon
  and we snapped to the closest road — treat `maxspeed_kmh` as approximate.

### `GET /v1/reviews/search` — FTS over review bodies

Returns reviews matching the query, joined to their parent place.

| Parameter | Type | Required | Default | Notes |
|---|---|---|---|---|
| `q` | string | yes | — | 1..200 chars |
| `category` | string | no | — | Slug / `all` / comma list — filters by parent place's category |
| `place_id` | string | no | — | Narrow to one place |
| `min_rating` | int | no | 0 | `1..5`; drops reviews below the star threshold |
| `limit` | int | no | 20 | 1..50 |
| `offset` | int | no | 0 | |
| `lang` | string | no | `en` | |

Each result carries a `snippet` field with matched tokens wrapped in
`<b>…</b>` for UI highlighting, the embedded parent place info, and a
`score`.

### `GET /v1/admin/usage` — per-key request counters

Returns aggregated per-`(key_prefix, endpoint, status)` counts. Auth
with the same `X-Api-Key`. Key prefixes are `sha256(key)[:8]` — safe
to log, never the plaintext.

### `GET /v1/health` — liveness probe

No auth. Returns `{"status":"ok"}`. Used by k8s probes + nginx
upstream health.

---

## Categories (slug enum)

Every request's `category` param accepts one of the 41 slugs below,
the literal `all`, or a comma-separated list (e.g. `coffee,bakery`).

**Daily-life core** (the 19 in `FEEDBACK.md §4`):
`coffee`, `restaurant`, `fast_food`, `bakery`, `grocery`, `mall`,
`fuel`, `ev_charger`, `car_wash`, `pharmacy`, `hospital`, `gym`,
`park`, `bank`, `atm`, `mosque`, `salon`, `laundry`, `post_office`.

**Additions** (server-side, omono can opt in as needed):
`library`, `bookstore`, `clinic`, `transit`, `juice`, `museum`,
`cultural_site`, `brunch`.

**Cuisine sub-categories**: `seafood`, `healthy_food`, `italian_food`,
`sushi`, `burger`, `pizza`, `shawarma`, `kabsa`, `mandi`,
`steakhouse`, `dessert`, `ice_cream`, `breakfast`, `indian_food`,
`asian_food`.

Unknown slug → `400 {"error":"unknown category: <slug>"}`.

---

## Synonyms (query-time expansion)

`/v1/search` and `/v1/reviews/search` expand query tokens against a
built-in synonym dictionary. Groups are Arabic ↔ English pairs +
transliteration variants + colloquial spellings. Examples:

| Typed | Expands to (OR-group) |
|---|---|
| `coffee` / `قهوة` / `قهوه` / `كوفي` | coffee, cafe, caffe, café, مقاهي, مقهي |
| `library` / `مكتبة` | library, books, reading, book cafe, مكتبة, مطالعة |
| `mosque` / `جامع` | mosque, masjid, مسجد, مساجد, جامع, جوامع |
| `american coffee` / `قهوة أمريكية` / `pour over` | filter/drip/v60/chemex/specialty coffee, قهوة مختصة, قهوة مقطرة |
| `museum` / `متحف` | museum, national museum, gallery, متاحف, معرض |
| `brunch` / `برانش` | brunch, all-day brunch, برانش كافيه |

Full list in `src/gplaces_parser/api/search_synonyms.py`.

---

## Scraper — how it works

1. **Tile Riyadh** — bbox from `.env` (default `24.50–25.05, 46.45–47.10`)
   split into ~30 named district centroids (see `districts.py`).
2. **Fan out queries** — for each district × slug × (Arabic query,
   English query) tuple, one search URL is opened in persistent
   Chromium.
3. **Scroll + extract** — the results feed is scrolled until the end
   marker; each card gives CID, name, lat/lng, URL, rating, review
   count, `business_status`, `open_now` hint, and subcategory.
4. **Review pass** — for each place, open the detail page, read
   address/phone/website/hours, click **Reviews → Newest**, scroll
   through every review, upsert.
5. **Resume** — every unit of work is a row in `scrape_jobs`, claimed
   with `SELECT … FOR UPDATE SKIP LOCKED`, so re-running after a
   crash picks up exactly where it left off.

CAPTCHA handling: the scraper pauses on Google's interstitials and
waits for you to solve them in the open Chromium window, then press
Enter. Session cookies survive across runs (`~/.cache/gplaces_parser/
chromium`).

---

## Prerequisites

- Python 3.12+
- Postgres 18 on `localhost:5432` (no PostGIS needed)
- A graphical desktop so Chromium can open for CAPTCHA solving

## Setup

```bash
cp .env.example .env
# edit .env — set GPLACES_API_KEY (openssl rand -hex 32) for the API

make install             # .venv + project + dev deps
make install-browser     # Chromium (~200 MB)
make db-create           # create role `gplaces` + db `gplaces` (sudo)
make migrate             # applies Alembic schema
```

## Running the scrape

```bash
make scrape-places       # pass 1 — fetch place cards across every district
make scrape-reviews      # pass 2 — detail + reviews for every place
make status              # totals + scrape_jobs breakdown
make psql                # ad-hoc SQL
```

Both passes are resumable. Rerun whenever; `SKIP LOCKED` prevents any
collision. Tuning knobs in `.env`: `RESULTS_PER_QUERY`,
`REVIEWS_PER_PLACE`, `SCRAPER_PAGE_TIMEOUT_MS`, `SCRAPER_MAX_SCROLLS`.

## Serving the API locally

```bash
make serve               # uvicorn on API_PORT (default 8000)
```

Spot-check:

```bash
KEY=<contents of .env GPLACES_API_KEY>
curl -H "X-Api-Key: $KEY" \
  'http://127.0.0.1:8000/v1/places?lat=24.7140&lon=46.6760&radius=1500&category=coffee&limit=10' | jq .
```

## Deploying

`make deploy` bundles everything for prod:

```bash
make deploy              # imports /tmp/gplaces-api.tar into k3s + rollout restart
```

The first deploy also needs nginx + certbot once:

```bash
make deploy-nginx        # copies homelab/nginx/api.omarss.net.conf
sudo certbot --nginx -d api.omarss.net   # only after a vhost change
```

For routine code deploys, just `make deploy` — no nginx touch, no
certbot.

---

## Schema

| Table | PK | Notes |
|---|---|---|
| `places` | `place_id` (Google CID) | Normalised columns + `raw` JSONB; FTS `search_tsv`; trigram indexes |
| `reviews` | `review_id` | FK → `places.place_id`, FTS `search_tsv` |
| `roads` | `osm_id` | Polygon stored as JSONB; bbox columns for index prefilter |
| `scrape_jobs` | `id` | Resumable job log; one row per (kind, scope) |
| `rating_history` | `id` | Append-only: every scrape's observed rating + review count |
| `status_history` | `id` | Append-only: every scrape's business_status + open_now + hours |
| `api_usage` | (key_prefix, endpoint, status, day) | Per-key request counters |

Handy queries:

```sql
-- Highest-rated cafes with ≥ 500 reviews
SELECT name, rating, reviews_count, full_address
FROM places
WHERE category = 'coffee' AND COALESCE(reviews_count, 0) >= 500
ORDER BY rating DESC NULLS LAST, reviews_count DESC NULLS LAST
LIMIT 20;

-- How has this place's rating drifted over time?
SELECT captured_at, rating, reviews_count
FROM rating_history
WHERE place_id = '0x3e2f…:0x8a7b…'
ORDER BY captured_at;
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make db-create` fails on `sudo -u postgres` | make sure the `postgres` role exists locally |
| `pydantic_core.ValidationError: gplaces_api_key` | empty `GPLACES_API_KEY` in `.env` — API refuses to start without one |
| Stuck `running` jobs after crash | `UPDATE scrape_jobs SET status='pending' WHERE status='running' AND started_at < now() - interval '1 hour';` then rerun |
| Failed jobs | `SELECT id, error FROM scrape_jobs WHERE status='failed';` → reset: `UPDATE scrape_jobs SET status='pending', attempts=0 WHERE id IN (…);` |
| Chromium won't launch (ProcessSingleton) | another scraper instance holds the profile — `pkill -f scrape-` or wait |
| `/v1/…` returns 400 "unknown category" after adding a new slug | the API image is stale — `make deploy` to pick up the new `ALLOWED_SLUGS` |
| `/v1/roads` empty after a GPS fix you're sure is on a road | polygons are tight; try `&snap_m=20` to grab the nearest within 20 m |
