# AGENTS.md — architecture + conventions

A standalone reference for any coding agent picking up this codebase.
Read `CLAUDE.md` first for the project-specific layout; this file covers
the deeper "why" and the conventions every change must follow.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Your crawler / API                     │
└─────────────────────────┬───────────────────────────────┘
                          │  async calls
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    JobCrawlerDB                          │  Facade  (db.py)
│  .sources  .companies  .recruiters  .skills .synonyms   │
│  .jobs  .job_locations  .postings  .dedupe              │
│  .fake_signals  .crawl  .geo  .reference  .search       │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│      psycopg_pool.AsyncConnectionPool (pool.py)         │
│  • configure: row_factory = dict_row                    │
│  • check (per-checkout): statement_timeout + trgm SETs  │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              PostgreSQL 18 (db_schema.sql)              │
└─────────────────────────────────────────────────────────┘
```

### Why a facade + repos?

A single `JobCrawlerDB` instance owns the pool and exposes one repo per
domain. Repos are simple async classes that:

* Take an `AsyncConnectionPool` in `__init__`.
* Hold **inline SQL** (no ORM, no query builder).
* Return typed Pydantic models from `models.py` — never raw `dict`s.

This keeps the lib explicit and grep-friendly. There are no hidden joins,
no lazy fetches, no N+1 surprises.

### Why no ORM?

The schema is bilingual, cluster-shaped, and uses Postgres-specific types
(tsvector with custom configs, trigram expression indexes, JSONB,
levenshtein). Every ORM I've tried makes those harder to read and harder
to optimise. Inline SQL is the right tool here.

### Async-only

* Async is the natural fit for a crawler that fans out concurrent fetches.
* psycopg3 supports both sync and async, but maintaining both doubles the
  test matrix without buying us anything.
* If a sync caller needs to call in, wrap with `asyncio.run(...)`.

## Conventions

### Strong typing

* Every function annotated. `mypy --strict` is part of CI (see `pyproject.toml`).
* Pydantic v2 for all read/write models.
* `StrEnum` mirroring every SQL `CREATE TYPE` — values match exactly so
  psycopg adapts to/from the Postgres enums without custom registration.
* Decimal for `numeric`, not float (banker's-round friendly).
* UUID for `uuid`. `bytes` for `bytea`.

### SQL conventions

* Named parameters (`%(name)s`), not positional.
* Cast `IS NULL` parameter checks: `%(loc)s::text IS NULL OR ...`.
* `ON CONFLICT` for all upserts; never SELECT-then-INSERT (race condition).
* `DEFERRABLE INITIALLY DEFERRED` only on the one cluster ↔ canonical_posting
  cycle.
* `RETURNING *` for write methods that return a model.
* Server-side cursors (`cur(... name="jcdb_stream")`) for any query expected
  to scan more than a few thousand rows.

### Comment policy

* Write comments only where the **why** is non-obvious.
* No `# Returns a Foo` — types document that.
* Document constraints, surprising trade-offs, and historical gotchas.

### Error handling

* Repos don't catch `psycopg.Error`. The caller's tx / retry layer owns that.
* Repos raise `KeyError` for "you asked me to update something that's gone"
  and `ValueError` for "your input is malformed".
* Schema CHECK violations bubble up as `psycopg.errors.CheckViolation` —
  caller is expected to know its own input ranges.

### Performance

* The pool size defaults are conservative (min 2, max 20). Tune via
  `JCDB_POOL_MAX_SIZE` for high-concurrency crawlers.
* Per-session `statement_timeout` defaults to 30s; surface it via Settings
  if you have legitimately long-running queries.
* GIN indexes (trigram + tsvector + JSONB) are expensive on write.
  `posting_skills_raw` and `crawl_fetches` are the highest-churn tables
  to keep an eye on if write throughput suffers.

## Adding features

### A new field on `jobs` or `job_postings`

1. Add the column in `db_schema.sql` (don't forget CHECK constraints).
2. Validate the schema still applies cleanly (see CLAUDE.md → "Working on
   the schema").
3. Add the field to the matching Pydantic model in `models.py` (both the
   read and write/upsert variants).
4. Wire the field into `repos/postings.py::_INSERT_SQL` + `_UPDATE_SQL` +
   `_insert_params`.
5. If the field should mirror posting → cluster, add it to
   `repos/jobs.py::recompute_canonical`.
6. Add an integration test covering both insert and the mirror.

### A new fake-signal kind

1. Add the value to `fake_signal_kind` enum in `db_schema.sql`.
2. Mirror it in `enums.FakeSignalKind`.
3. If it needs special-case verdict logic (e.g., recycled-overrides-suspicious),
   add it in `repos/fake_signals.py::recompute_score`.
4. Add a test in `tests/test_dedupe_fake.py`.

### A new external data source

1. `db.sources.upsert(slug=..., kind=..., trust_weight=...)` from your
   bootstrap script. `trust_weight` directly affects which posting wins
   `recompute_canonical` — ATS sites near 1.0, aggregators around 0.5.
2. Add a scraper module in your *crawler* repo (this lib is data-access only).

### A new heuristic in `detect_ai_generation`

* Pure functions only — no I/O, no globals.
* Mark deterministic, doc-string the heuristic in plain English, add a unit
  test in `tests/test_ai_generation.py`.

## Open-source-first (priority: cost + accuracy)

This project intentionally avoids paid SaaS / GenAI APIs. The two
priorities are **zero recurring cost** and **deterministic accuracy** (you
can audit a local model; you can't audit a vendor's black box).

Concrete rules:

* **No paid LLM API** (OpenAI / Anthropic / Bedrock / etc.) in core code paths.
  If a feature genuinely needs an LLM, it goes behind an opt-in flag and
  the default is a local OSS alternative.
* **No paid email API** (Resend / Mailgun / SES). Alerts use plain SMTP
  via `aiosmtplib` — Gmail SMTP with an app password is the default.
* **No paid scraping service** (Bright Data / Apify / ScrapingBee) for
  the default crawler path. Polite `httpx` first, Playwright second; if
  a site genuinely requires a residential-proxy provider, that crawler
  is opt-in and disabled by default.
* **No paid geo / payments / vector DB**. Postgres + `pg_trgm` +
  `fuzzystrmatch` cover search; `pgvector` if we ever need embeddings.

OSS libraries the project already uses (all MIT/BSD/Apache-2):
* `psycopg`, `pydantic`, `httpx`, `selectolax`, `lxml`, `tenacity`,
  `aiosmtplib`, `python-dotenv`, `fastapi`, `uvicorn`.

When adding ML-shaped functionality, default choices:

| Capability                 | OSS default                                          |
| ---                        | ---                                                  |
| AI-generated text detect   | heuristics in `ai_generation.py` (already shipped)   |
| Skill / entity extraction  | `spaCy` + a small en/ar pipeline (offline)           |
| Semantic search ranking    | `sentence-transformers` (all-MiniLM-L6-v2) + `pgvector` |
| Arabic ↔ English translation | `argos-translate` or HuggingFace MarianMT (offline) |
| AI text classification     | `scikit-learn` / `lightgbm` on local features        |

Each of these runs locally, fits in a container under a few hundred MB,
and has accuracy adequate for noise-reduction on job postings. If the
default proves insufficient for a use case, the discussion is "which OSS
model do we swap in?" not "which paid API do we sign up for?".

## Things to avoid

* **Paid SaaS / GenAI APIs** in the default code path. See "OSS-first" above.
* **Sync APIs.** Async-only.
* **ORMs.** Inline SQL keeps optimisation latitude.
* **Hidden state.** Settings is frozen; repos are stateless except for the pool.
* **Catching `psycopg.Error` to hide details.** Let it propagate.
* **Print / log inside repos.** Observability is the caller's job.
* **String-formatting user input into SQL.** Always use named placeholders
  (one exception: `SET` statements in `pool.py`, which can't take binds —
  formatted from typed Settings, never user input).
* **Breaking-change releases without explicit user confirmation.**
