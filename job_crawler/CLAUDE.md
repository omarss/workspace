# CLAUDE.md — orientation for Claude inside `job_crawler`

This repo contains:

1. `db_schema.sql` — Postgres 18 schema for a SA-focused job crawler.
2. `src/job_crawler_db/` — async Python facade over that schema.
3. `tests/` — integration tests against a real PostgreSQL container.

If the user asks anything DB-shaped, **start here, not at guesses.**

---

## Schema-level mental model

* **Cluster dedupe**: every crawled URL becomes one `job_postings` row;
  one `jobs` row represents the *real job* and is the parent of N postings.
* **Companies / skills / synonyms**: canonical row + alias table + (for
  synonyms) a group table. `normalize_text()` folds Arabic letterforms,
  strips diacritics, lowercases + unaccents Latin so fuzzy matching is
  bilingual from one index.
* **Search** lives in three layers — tsvector FTS, trigram (`%` / `<%`),
  and (in `skills`) levenshtein. Trigram indexes are on the *normalized*
  expression, not the raw column.
* **Saudi-first geography**: `sa_regions` + `sa_cities` + `countries`.
  Multi-office clusters use `job_locations`.
* **Recruiters** and **hiring managers** are tracked separately —
  recruiter = HR/agency person posting the listing; hiring manager =
  the actual hiring person (LinkedIn URL nullable).

See the top of `db_schema.sql` for the canonical model overview.

## Lib layout

```
src/job_crawler_db/
├── __init__.py          public exports
├── db.py                JobCrawlerDB facade — entry point
├── settings.py          dataclass Settings; from_env()
├── pool.py              build_pool() — AsyncConnectionPool wrapper
├── schema.py            apply_schema(conn)
├── hashing.py           normalize_url, url_hash, content_hash
├── ai_generation.py     detect_ai_generation() heuristic
├── enums.py             every CREATE TYPE mirrored as StrEnum
├── models.py            Pydantic v2 models for every entity
└── repos/
    ├── base.py          Repo super-class (fetchone/fetchall/stream/transaction)
    ├── sources.py
    ├── companies.py     create / resolve / aliases / source profiles
    ├── recruiters.py
    ├── skills.py        find() = trigram + levenshtein + alias join
    ├── synonyms.py      groups + terms + expand()
    ├── jobs.py          create_from_posting / recompute_canonical / merge
    ├── job_locations.py
    ├── postings.py      upsert() — the crawler hot path
    ├── dedupe.py        pairwise edges
    ├── fake_signals.py  add() + recompute_score()
    ├── crawl.py         runs + per-fetch ledger
    ├── geo.py           regions + cities + fuzzy city lookup
    ├── reference.py     countries, industries, categories
    └── search.py        find_jobs() — the big ranked search
```

## Common gotchas (already fixed but worth knowing)

* **`SET` rejects bind parameters** at the PG protocol level. Inline the
  literal value into the SQL string (`pool.py::_on_checkout`).
* **psycopg3 doesn't allow multi-statement parameterised `execute()`** —
  one statement per call.
* The pool's `configure` callback sets `conn.row_factory = dict_row`, so
  every cursor returns dicts by default. Tuple-style `row[0]` will raise
  KeyError; use `row["id"]`.
* `IS NULL` checks on parameter placeholders confuse the planner —
  always cast: `%(loc)s::text IS NULL`, `%(skill_ids)s::uuid[] IS NULL`.
* `raw_payload jsonb NOT NULL` — pass `'{}'` rather than `None` even on
  empty payloads (the column default only kicks in when omitted entirely).
* The schema CHECK on `job_fake_signals.weight` is `[-1, 1]`. Per-signal
  cap is intentional; signals compound through the sigmoid in
  `recompute_score`.

## Adding a new repo

1. Add a file under `src/job_crawler_db/repos/your_repo.py` subclassing
   `Repo`.
2. Use `self._fetchone` / `_fetchall` / `_stream` / `_execute` — they
   handle the pool checkout + row factory.
3. Add a typed model in `models.py` if it doesn't exist.
4. Wire it into `db.py` as a lazy `@property`.
5. Add tests in `tests/`. Use `seeded_reference` if your repo needs
   countries/regions/cities/sources; otherwise the bare `db` fixture
   (which seeds only Saudi Arabia for the `country_code='sa'` FK default).

## Running things

```bash
make help        # list targets
make test        # full pytest run via uv
make lint        # ruff check
make typecheck   # mypy --strict
```

There's no `make run` — this is a library, not a service.

## Working on the schema

After editing `db_schema.sql`:

```bash
docker run --rm -d --name jc_check -e POSTGRES_PASSWORD=x postgres:18-alpine
docker exec -i jc_check psql -U postgres -v ON_ERROR_STOP=1 < db_schema.sql
docker rm -f jc_check
```

If you change a column or enum used by a model:

1. Update `enums.py` (if a new enum value).
2. Update `models.py` (add the field).
3. Update the relevant repo's INSERT/UPDATE SQL **and** its param dict.
4. Update `recompute_canonical` in `repos/jobs.py` if the field should
   mirror up from the posting to the cluster.
5. Update or add an integration test that exercises the new field.

## Do not

* Re-introduce ORMs (SQLAlchemy etc.). Repos hold inline SQL on purpose.
* Add sync APIs. The lib is async-only.
* Print or log inside repos. The caller owns observability.
* Catch `psycopg.Error` inside repos. Let it propagate to the caller.
