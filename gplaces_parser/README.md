# gplaces_parser

Two halves of one personal product:

1. **Scraper** — a Playwright-driven Chromium that crawls Google Maps
   results for Arabic categories across a Riyadh tile grid, captures
   places + reviews, and upserts everything into Postgres 18.
2. **API** — a small FastAPI service (`GET /v1/places`) that serves
   those places by lat/lon/radius/category to the omono Android client.
   Contract: [FEEDBACK.md](./FEEDBACK.md).

## How the scraper works

1. **Tile Riyadh** — bbox from `.env` (default `24.50–25.05, 46.45–47.10`)
   is split into ~3 km cells.
2. **Fan out queries** — for each tile × 19 Arabic category queries
   (see `src/gplaces_parser/categories.py`: `مقاهي، مطاعم، حدائق…`) a
   Google Maps search URL is opened in persistent Chromium.
3. **Scroll + extract** — the results feed is scrolled until the end
   marker; each result card gives us CID, name, lat/lng, and url.
4. **Review pass** — for each place, open the detail page, read
   address/phone/rating/website, click **Reviews → Newest**, scroll
   through every review, and upsert.
5. **Resume** — every unit of work is a row in `scrape_jobs`, claimed
   with `SELECT … FOR UPDATE SKIP LOCKED`, so re-running after a
   crash picks up exactly where it left off and multiple terminals can
   share the queue without stepping on each other.

CAPTCHA handling: the scraper pauses on Google's interstitials and
waits for you to solve them in the open Chromium window, then press
Enter. Session cookies survive across runs (`~/.cache/gplaces_parser/
chromium`), so the rate limiter stays quieter over time.

## Prerequisites

- Python 3.12+
- Postgres 18 on `localhost:5432` (no PostGIS needed — haversine runs
  in plain SQL)
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

## Running the crawl

```bash
make scrape-places       # pass 1 — fetch place cards across the bbox
make scrape-reviews      # pass 2 — detail + reviews for every place
make status              # totals + scrape_jobs breakdown
make psql                # ad-hoc SQL
```

Both passes are resumable. To parallelise, run `make scrape-places` in
several terminals — each launches its own Chromium and each `SKIP
LOCKED` transaction claims a disjoint slice of the queue.

## Serving the API

```bash
make serve               # runs `uvicorn` on $API_PORT (default 8000)
```

Spot-check:

```bash
curl -H "X-Api-Key: $GPLACES_API_KEY" \
  'http://127.0.0.1:8000/v1/places?lat=24.7140&lon=46.6760&radius=1500&category=coffee&limit=10' | jq .
```

## Deploying

```bash
make image-build image-load      # build and import into the local k3s
make k8s-apply                   # apply homelab/apps/api-places
# then, on the host:
sudo cp ../homelab/nginx/api.omarss.net.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/api.omarss.net.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.omarss.net
```

Public URL after that: `https://api.omarss.net/v1/places` (see
`FEEDBACK.md` for the contract omono speaks).

## Schema

| Table | PK | Notes |
|-------|-----|-------|
| `places` | `place_id` (Google CID) | Normalised columns + full `raw` JSONB |
| `reviews` | `review_id` | FK → `places.place_id`, full `raw` JSONB |
| `scrape_jobs` | `id` | Resumable job log, one row per (kind, scope) |

Handy queries:

```sql
-- Top-rated cafes in Riyadh with ≥ 100 reviews
SELECT name, rating, reviews_count, full_address
FROM places
WHERE category = 'coffee' AND COALESCE(reviews_count, 0) >= 100
ORDER BY rating DESC NULLS LAST, reviews_count DESC NULLS LAST
LIMIT 20;

-- Every 1-star review, newest first
SELECT r.published_at, r.rating, r.text, p.name
FROM reviews r JOIN places p USING (place_id)
WHERE r.rating = 1
ORDER BY r.published_at DESC NULLS LAST
LIMIT 50;
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make db-create` fails on `sudo -u postgres` | make sure the `postgres` role exists locally |
| `pydantic_core.ValidationError: gplaces_api_key` | empty `GPLACES_API_KEY` in `.env` — API refuses to start without one |
| Stuck `running` jobs after crash | `UPDATE scrape_jobs SET status='pending' WHERE status='running' AND started_at < now() - interval '1 hour';` then rerun |
| Failed jobs | `SELECT id, error FROM scrape_jobs WHERE status='failed';` → reset: `UPDATE scrape_jobs SET status='pending', attempts=0 WHERE id IN (…);` |
| Chromium won't launch (ProcessSingleton) | another scraper instance already holds the profile — `pkill -f scrape-` or wait |
