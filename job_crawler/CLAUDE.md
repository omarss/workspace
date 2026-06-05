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
* **Country-scoped geography**: `countries` + `regions` (PK
  `(country_code, code)`) + `cities` (composite FK
  `(country_code, region_code) → regions`, MATCH SIMPLE so both fields
  are populated together or both NULL). `jobs`, `job_postings`, and
  `job_locations` each carry `city_id` + the composite, so any one of
  city / region / country can be filtered on. Saudi is the default
  tenant (`country_code` defaults to `'sa'` on `jobs`/`job_postings`)
  but the schema is no longer SA-only — UAE / Bahrain / Kuwait / Oman /
  Qatar regions + cities seed alongside SA via
  `discover/manual_seed.py`. Multi-office clusters still use
  `job_locations`. **NB:** the old `sa_regions` / `sa_cities` tables
  were renamed to `regions` / `cities` in PR #18; live DBs need
  `make db-migrate-geo CONFIRM=yes-migrate-geo` once after pulling.
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
* **HTML decode order**: when a source double-encodes its HTML (Greenhouse
  returns `&lt;p&gt;` inside JSON), feeding it straight to `HTMLParser`
  produces a no-op strip — the parser sees `&lt;p&gt;` as plain text.
  Always `html.unescape()` BEFORE `HTMLParser.text()`. Caught in
  Finding 11; guarded by `tests/test_parsers.py`.
* **`SourcesRepo.upsert` preserves `crawl_enabled` by default**: the
  `crawl_enabled` kwarg is `bool | None = None`; the SQL is
  `COALESCE(%s, sources.crawl_enabled)` on conflict. The runner calls
  upsert on every run with no kwarg — without COALESCE that silently
  re-enables anything `crawler_health.mark_broken()` had disabled.
  Pass an explicit `True`/`False` only from operator-facing CLIs.
* **Composite (country_code, region_code) FK is MATCH SIMPLE by default
  in PG** — a row with `region_code = NULL` skips the FK check entirely,
  so a country-only posting ("Remote, UAE") is legal without inventing
  a placeholder region. `country_code` is `NOT NULL DEFAULT 'sa'`, so
  the upsert path always has a country to mirror up to the cluster.
* **Wikidata fails loud**: `discover/wikidata.fetch_and_load` raises
  `WikidataFetchError` on HTTP/JSON failure (was: returned `(0,0,0)`
  and looked like success). `cli/discover.py` translates it to exit-1
  + SMTP alert so the weekly CronJob can't be silently broken.
  Wrapped in tenacity (3 attempts, 2-30s backoff) for transient 5xx.
* **`resolve_city` takes a `country_code` hint**: without it, fuzzy
  matching crosses borders — "Al Rayyan" hits both SA and QA, "Ras
  Al Khair" hits UAE Ras Al Khaimah. Crawlers that already know the
  country (ATS feeds for a SA-only company; GCC-tagged ATS detail
  page) must pass `parsed.country_code` into `resolve_city`.
* **Wuzzuf selector drift gate**: `boards/wuzzuf.py::parse` returns
  `None` (counts as a parse failure) when both `description` and
  `raw_company_name` are missing. Before this gate the runner happily
  wrote 15/15 title-only rows with no usable body. Apply the same
  pattern to any future board crawler whose selectors are CSS-hashed
  or otherwise fragile.
* **Mypy invariance trap**: `list[X]` is invariant — a function
  declared `(rows: list[Mapping[str, Any]])` rejects the
  `list[dict[str, Any]]` that `_fetchall` returns. Repo helpers use
  `Sequence[Mapping[str, Any]]` (covariant) instead. Same trick for
  `dict` parameters that need to accept a narrower value type. When
  in doubt: `Sequence`/`Mapping` for inputs (covariant), `list`/`dict`
  for outputs (the caller knows the concrete type).
* **`cur.row_factory` + mypy**: the pool's `configure` callback sets
  `conn.row_factory = dict_row` at runtime, but mypy doesn't see
  through that to the cursor type. Pass `row_factory=dict_row`
  explicitly when calling `conn.cursor(...)` if the cursor uses
  `row["name"]` indexing — otherwise mypy types it as the default
  tuple-row cursor and the indexing fails strict mode.
* **Don't reassign bare `_`**: `_ = X` for one symbol then `_ = Y`
  for another confuses mypy's type narrowing — it tries to unify the
  types under a single binding. Either give each keepalive a distinct
  name (`_KEEP_DATETIME = datetime`) or use `__all__`.
* **`**kwargs` unpack into a dataclass loses field-name info**: mypy
  matches each value-type against parameter types in order, so
  `**dict[str, str|None]` unpacked into a dataclass mid-call gets
  matched against the wrong fields and complains. List the fields
  explicitly (see `core/jsonld.py::_parse` for a worked example).

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
* Add `RESEND_API_KEY` / `SENDGRID_*` / `MAILGUN_*` / `SES_*` for alerts.
  Alerts go through plain SMTP via `alerts/email.py`; the OSS-first
  contract is enforced in the Makefile comment block.
* Put GCC cities under SA Eastern region "as a placeholder". The
  composite FK on `cities` makes that impossible at the schema level
  now; if a new GCC city is needed, seed its real `(country_code,
  region_code)` in `discover/manual_seed.py::_CITIES` and add the
  country to `_ensure_reference` if it's not already there.
* Hardcode `country_code = 'sa'` in any cluster-creation SQL. The
  posting carries it; mirror it via `jobs.create_from_posting` and
  `recompute_canonical`. `jobs.country_code` is still
  `NOT NULL DEFAULT 'sa'` so the column never goes blank, but the
  value comes from data, not literals.

## Audit remediation status (2026-05)

A random-scope audit (`FINDINGS.md` on the openbao branch) surfaced 18
findings. Status:

| # | Severity | Status   | Where                                                   |
|---|----------|----------|---------------------------------------------------------|
| 1, 10 | High | DONE PR#18 | `cities` country-scoped; GCC seeded under real countries |
| 9 | High | DONE PR#18 | `region_code` plumbed through ParsedPosting → upsert → cluster |
| 14 | High | DONE PR#18 | `SourcesRepo.upsert` COALESCEs `crawl_enabled`           |
| 11 | Med  | DONE PR#20 | Greenhouse `html.unescape` before `HTMLParser`           |
| 12 | Med  | DONE PR#20 | Wuzzuf required-field gate + Mihnati promo filter (Mihnati retired in 2026-06) |
| 13 | Med  | DONE PR#20 | `to_upsert` already unescapes; regression test added     |
| 4  | Med  | DONE PR#21 | Wikidata `WikidataFetchError` + tenacity + nonzero exit  |
| 5  | Med  | DONE PR#21 | Seed CSV duplicate audit + whitelist test                |
| 7  | Low  | DONE PR#21 | Makefile RESEND → SMTP_*                                 |
| 8  | Low  | DONE PR#21 | `report_counts.sql` uses `normalize_text` grouping       |
| 18 | Low  | DONE PR#21 | Stale `(stub)` labels removed from Makefile header       |
| 15 | High | DONE pre-audit | All stubs implemented before the audit doc landed   |
| 3  | Med  | DONE PR#23 | `JC_PROXY_STATE_FILE` env + emptyDir mount on CronJobs   |
| 6  | Low  | DONE PR#23 | `UVICORN_FORWARDED_ALLOW_IPS` env; default 127.0.0.1     |
| 16 | Med  | DONE PR#24 | `BaseCrawler.normalize()` + 18 placeholder bodies gone   |
| 17 | Med  | DONE PR#24 | Canary returns `Literal["ok","fail","skipped_no_canary"]` |
| 2  | High | DONE PR#26 | mypy strict reaches zero errors; `make check` enforces it |

**All 18 findings closed.** Subsequent audit cycles should add new rows
beneath this table; never remove rows once they're done — they double as
a changelog of the project's quality-bar history.

When picking up the remaining work, check this table first — it's
faster than re-running the audit, and the PR numbers link to the design
context for each fix.

## Working in worktrees (post-audit workflow)

The monorepo at `/home/omar/workspace_personal` hosts ~12 projects on
sibling branches. To keep `job_crawler` PRs isolated from in-flight
work on other projects:

```bash
git fetch origin main
git worktree add /home/omar/workspace_personal-worktrees/job_crawler-<topic> \
  -b job_crawler/<topic> origin/main
cd /home/omar/workspace_personal-worktrees/job_crawler-<topic>/job_crawler
# … work, commit, push, open PR …
gh pr merge <N> --merge --delete-branch   # may print
#   "fatal: 'main' is already used by worktree at '/home/omar/jc-wt'"
# That error is COSMETIC — the PR merges on GitHub. It only fails to
# update the local main checkout (because `/home/omar/jc-wt` has it).
# Verify with `gh pr view <N> --json state,mergedAt`.
git worktree remove ../<this worktree>
```

PR conventions enforced for this project:

* Branch name: `job_crawler/<short-topic>` (matches the path-filter the
  saas CI uses to NOT run on job_crawler PRs).
* Title: `fix(<scope>): lowercase ≤50 chars` — one of `geo`, `parsers`,
  `wikidata`, `seed`, `sources`, `docs`.
* Body: link the FINDINGS.md item being fixed; one section per finding
  when batching; explicit "Test plan" checklist.
* Always sync with `origin/main` (rebase) before pushing; this branch
  has been moving 5+ commits/day from other projects.
* Add the `ready` label after opening the PR. There's currently no CI
  gated on `job_crawler/**` paths (only `saas/**` is gated), so a green
  `make test` + `make lint` locally is the merge bar.
* Two atomic commits beats one mega-commit, even for related fixes —
  each finding usually maps to its own commit so `git log --grep
  "Finding N"` finds the change later.

## Live-DB rollout reminders

* After PR #18: run once on the live host (companies kept; jobs/postings
  wiped):

  ```bash
  make -C job_crawler db-clear CONFIRM=1
  make -C job_crawler db-migrate-geo CONFIRM=yes-migrate-geo
  make -C job_crawler discover-seed
  ```

* The schema is **not** idempotent (`CREATE TABLE`, no `IF NOT EXISTS`).
  `make db-apply` is for fresh databases only; migrations live under
  `scripts/migrate_*.sql` and get a one-shot `make` target.

* `db-clear` (crawl-data only) is safe to re-run any time — companies,
  skills, sources, geo, reference data all survive.
  `db-clear-all` additionally wipes companies + recruiters + aliases;
  reserve for "start completely fresh" moments.

## Lessons captured from the audit

* **Audit first, fix in waves.** A 100-row `SELECT * FROM jobs ORDER BY
  random()` plus per-source rollups exposed contamination
  (GCC-as-Saudi, region NULL, HTML in descriptions) that no unit test
  would catch. Make a habit of running `scripts/report_counts.sql` plus
  a similar random sample after each release before declaring victory.

* **Reference data fixes pair with a data wipe.** Renaming
  `sa_cities → cities` would have been a multi-week migration if
  companies depended on `headquarters_city_id` — they didn't (all NULL
  in production), and clearing jobs/postings was acceptable because
  most rows were already wrong. Confirm the "what data is real" question
  before designing the migration.

* **Findings → tests, not docs.** Every fix in PRs #18/#20/#21 has at
  least one regression test (`test_geo_country_region.py`,
  `test_parsers.py`, `test_seed_data_quality.py`). The findings
  themselves stayed in `FINDINGS.md` on the openbao branch — the
  durable artefact is the test.

* **Use the whitelist pattern when reality is messy.** The seed CSV has
  5 deliberate duplicate identifiers (parent + subsidiary share a
  LinkedIn URL until an `alias_of` column lands). The test enforces
  "no NEW duplicates" with a documented exception list, instead of
  blocking the PR until the data is perfect.
