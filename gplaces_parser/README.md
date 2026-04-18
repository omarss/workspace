# gplaces_parser

Crawl every public Google Maps place and review in Riyadh (in Arabic)
via [Outscraper](https://outscraper.com), stored in a local Postgres 18
database. Resumable, idempotent, and throttled for concurrent workers.

## How it works

1. **Tile Riyadh** — bounding box `(24.50–25.05, 46.45–47.10)` is split into
   ~3 km cells (~400 tiles).
2. **Fan out queries** — for each tile × ~40 Arabic category queries
   (`مطاعم`, `مقاهي`, `حدائق`, …) one Outscraper async job is submitted.
3. **Upsert places** — results land in `places`, deduped by `place_id`;
   raw JSON kept in a `JSONB` column.
4. **Fan out reviews** — for each new place, fetch up to 2000 reviews
   (`sort=newest`) and upsert into `reviews`.
5. **Resume** — `scrape_jobs` tracks every (kind, scope) so a rerun only
   picks up pending work; `SKIP LOCKED` makes multi-worker safe.

## Prerequisites

- Python 3.12+
- Postgres 18 running locally on `localhost:5432` (already installed on this
  machine)
- An Outscraper API key

## Setup

```bash
cp .env.example .env
# then put your OUTSCRAPER_API_KEY in .env

make install         # creates .venv, installs the package + deps
make db-create       # creates role `gplaces` and db `gplaces` (uses sudo)
make migrate         # applies Alembic schema
```

## Running the crawl

```bash
make scrape-places   # Pass 1 — fetch all places across Riyadh
make scrape-reviews  # Pass 2 — fetch reviews for every place with >0 reviews
make status          # Show totals + scrape_jobs breakdown
```

Both passes are resumable — re-run after a crash and they pick up where they
left off. To inspect state directly:

```bash
make psql
```

## Schema

| Table | PK | Notes |
|-------|-----|-------|
| `places` | `place_id` | Normalized columns + full `raw` JSONB |
| `reviews` | `review_id` | FK → `places.place_id`, full `raw` JSONB |
| `scrape_jobs` | `id` | Resumability: `(kind, category, tile)` or `(kind, place_id)` |

Handy queries:

```sql
-- Top rated cafes in Riyadh with ≥ 500 reviews
SELECT name, rating, reviews_count, full_address
FROM places
WHERE category = 'cafes' AND reviews_count >= 500
ORDER BY rating DESC, reviews_count DESC
LIMIT 20;

-- Newest 1-star reviews
SELECT r.published_at, r.rating, r.text, p.name
FROM reviews r JOIN places p USING (place_id)
WHERE r.rating = 1
ORDER BY r.published_at DESC NULLS LAST
LIMIT 50;
```

## Cost control

Outscraper charges per result. To do a dry-run before spending credit,
limit the scope via `.env`:

- Smaller bounding box (e.g. one Riyadh district)
- `TILE_KM=5.0` instead of `3.0` (fewer tiles)
- Trim `src/gplaces_parser/categories.py` to 3–5 categories
- `RESULTS_PER_QUERY=100` and `REVIEWS_PER_PLACE=200`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make db-create` fails on `sudo -u postgres` | Make sure `postgres` role exists and you can `sudo` |
| `pydantic_core.ValidationError: outscraper_api_key` | Missing/too-short key in `.env` |
| Stuck `running` jobs after a crash | `UPDATE scrape_jobs SET status='pending' WHERE status='running' AND started_at < now()-interval '1 hour';` then re-run |
| Failed jobs | `SELECT id, error FROM scrape_jobs WHERE status='failed';` — reset with `UPDATE scrape_jobs SET status='pending', attempts=0 WHERE id IN (...);` |
