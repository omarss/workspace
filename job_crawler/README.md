# job-crawler-db

Async PostgreSQL facade for the `job_crawler` schema — the single entry
point your crawler, dedupe pipeline, and search API talk to.

* **Async-only** (built on `psycopg[binary,pool]` AsyncConnectionPool).
* **Strongly typed** — Pydantic v2 models for every entity, enums mirroring
  every SQL `CREATE TYPE`.
* **Saudi-Arabia first** geography + bilingual (Arabic / English) search.
* **Cluster dedupe model**: per-source `job_postings` collapse into one
  canonical `jobs` row, with pairwise similarity evidence + per-cluster
  fake-signal evidence driving the verdict.
* **Comprehensive search**: tsvector FTS (English with `unaccent` +
  stemming, Arabic with letterform normalisation) **+** trigram fuzzy
  match **+** levenshtein for typos **+** synonym expansion.
* **AI-generated description detection** as a built-in heuristic.
* **OSS-first, zero paid APIs** — alerts via plain SMTP (`aiosmtplib`),
  no Resend/Mailgun/SES, no paid LLM, no paid scraping service.
* **No ORM** — repos hold inline SQL so every query is greppable.

---

## Install

```bash
uv add job-crawler-db                  # consumer
# or, in this repo:
uv venv && uv pip install -e ".[dev]"  # development
```

Requires Python ≥ 3.12 and PostgreSQL ≥ 18.

## Bootstrap

The schema lives in `db_schema.sql` at the repo root. The lib doesn't ship
a migration tool — apply the schema once on a fresh database:

```python
import asyncio
import psycopg
from job_crawler_db import apply_schema

async def main() -> None:
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        await apply_schema(conn)

asyncio.run(main())
```

## Configure

All knobs are env-driven via `JCDB_*`. The only required variable is the DSN.

| Env var | Default | Purpose |
| --- | --- | --- |
| `JCDB_DSN`                            | — (required) | libpq connection string |
| `JCDB_POOL_MIN_SIZE`                  | 2  | min pool connections |
| `JCDB_POOL_MAX_SIZE`                  | 20 | max pool connections |
| `JCDB_POOL_TIMEOUT`                   | 30 | seconds to wait for a free conn |
| `JCDB_POOL_MAX_IDLE`                  | 600 | close idle conns older than this |
| `JCDB_POOL_MAX_LIFETIME`              | 3600 | recycle long-lived conns |
| `JCDB_STATEMENT_TIMEOUT_MS`           | 30000 | per-query timeout |
| `JCDB_TRGM_SIMILARITY_THRESHOLD`      | 0.30 | `pg_trgm` `%` threshold |
| `JCDB_TRGM_WORD_SIMILARITY_THRESHOLD` | 0.45 | `pg_trgm` `<%` threshold |
| `JCDB_APPLICATION_NAME`               | `job_crawler_db` | shows in `pg_stat_activity` |

## Quick start

```python
import asyncio
from decimal import Decimal
from job_crawler_db import (
    JobCrawlerDB, JobPostingUpsert,
    EmploymentType, ExperienceLevel, SalaryPeriod, WorkArrangement,
)

async def main() -> None:
    async with JobCrawlerDB.from_env() as db:
        # 1. Source bootstrap
        linkedin = await db.sources.upsert(
            slug="linkedin", display_name="LinkedIn",
            kind="aggregator", base_url="https://linkedin.com",
            trust_weight=0.60,
        )

        # 2. Resolve / create the employer
        company = await db.companies.resolve(
            raw_name="Acme Saudi", source_id=linkedin.id,
            source_profile_url="https://linkedin.com/company/acme",
        )

        # 3. Ingest a posting (idempotent on source + external_id)
        posting = await db.postings.upsert(JobPostingUpsert(
            source_id=linkedin.id,
            source_job_external_id="li-9001",
            canonical_url="https://linkedin.com/jobs/9001",
            title="Senior Python Engineer",
            description="Build scalable Django services on PostgreSQL.",
            company_id=company.id,
            employment_type=EmploymentType.full_time,
            work_arrangement=WorkArrangement.hybrid,
            experience_level=ExperienceLevel.senior,
            salary_min=Decimal("20000"), salary_max=Decimal("28000"),
            salary_currency="SAR", salary_period=SalaryPeriod.monthly,
            hiring_manager_linkedin_url="https://linkedin.com/in/sarah-al-otaibi",
        ))

        # 4. Cluster it (or attach to an existing cluster)
        cluster = await db.jobs.create_from_posting(posting.id)

        # 5. Search
        hits = await db.search.find_jobs("python engineer")
        for h in hits:
            print(h.score, h.job.title_en)

asyncio.run(main())
```

---

## The facade

`JobCrawlerDB` exposes one repo per domain area:

| Attribute        | Owns                                                     |
| ---              | ---                                                      |
| `.sources`       | `sources` table — crawl targets                          |
| `.companies`     | `companies` + aliases + per-source profile pages         |
| `.recruiters`    | `recruiters` (LinkedIn / Bayt individual posters)        |
| `.skills`        | `skills` + `skill_aliases`                               |
| `.synonyms`      | `synonym_groups` + `synonym_terms` (query expansion)     |
| `.jobs`          | `jobs` (clusters) + `job_skills`                         |
| `.job_locations` | `job_locations` (multi-office clusters)                  |
| `.postings`      | `job_postings` + snapshots + raw skills + apply channels |
| `.dedupe`        | `posting_duplicate_edges`                                |
| `.fake_signals`  | `job_fake_signals` + cluster-score recompute             |
| `.crawl`         | `crawl_runs` + `crawl_fetches`                           |
| `.geo`           | SA regions + cities (fuzzy city lookup)                  |
| `.reference`     | countries, industries, job categories                    |
| `.search`        | ranked job search (FTS + trigram + synonym + filters)    |

Every method returns either a typed model from `job_crawler_db.models`
or a primitive. Repos never expose raw psycopg rows.

## Search

The search facade combines five recall layers and one weighted ranker:

1. **English FTS** with `english_unaccent` config (`café` → `cafe` → `cafes` via stem).
2. **Arabic FTS** over `simple` parser fed `normalize_ar()`-folded text.
3. **Trigram fuzzy** (`%` and `<%`) on the *normalized* expression.
4. **Levenshtein** for transposition typos that trigram misses (skill search).
5. **Synonym expansion** via `synonym_terms` (`k8s` → `kubernetes`, `swe` → `software engineer`, …).

Ranking is a transparent weighted sum:

```text
score = 0.35 * ts_rank(search_en, q_en)
      + 0.35 * ts_rank(search_ar, q_ar)
      + 0.10 * word_similarity(title_en, q)
      + 0.10 * word_similarity(title_ar, q)
      + 0.05 * ln(posting_count + 1)
      + 0.05 * max(0, 1 − age_days / 30)
```

```python
hits = await db.search.find_jobs(
    "k8s engineer riyadh",
    city_id=riyadh.id,
    employment_type=EmploymentType.full_time,
    min_salary=20000,
    required_skill_ids=[kubernetes.id, go.id],
    limit=25,
)
```

Filter-only mode (no query) returns clusters matching the structured filters,
ranked by recency.

## Dedupe + fake-score

The dedupe pipeline:

1. Crawler upserts a posting (idempotent on `source_id + external_id`).
2. Pairwise similarity is detected — exact URL hash, content hash, near-content
   trigram, or cross-source repost. Each becomes a `posting_duplicate_edges` row.
3. The clustering job groups strongly-connected postings into a `jobs` cluster.
4. `db.jobs.recompute_canonical(job_id)` mirrors the highest-trust posting's
   fields into the cluster.
5. Fake heuristics fire signals (`db.fake_signals.add(...)`).
6. `db.fake_signals.recompute_score(job_id)` sums the signed weights, squashes
   via sigmoid, and updates `verdict` + `legit_score`.

## AI-generated description detection

```python
from job_crawler_db import detect_ai_generation

result = detect_ai_generation(posting.description)
if result.is_likely_ai():
    await db.fake_signals.add(
        cluster_id, "ai_generated_description",
        weight=max(-1.0, -result.score), details={"hits": result.hits},
    )
```

Heuristics counted (each detailed in `ai_generation.py`):

* LLM phrase markers (`embark on a journey`, `dynamic landscape of`, …)
* Em-dash density (LLMs love them)
* Triple-adjective tics (`innovative, collaborative, dynamic`)
* Verbatim equal-opportunity / closing boilerplate
* Sentence-length burstiness (low variance = more AI-like)
* Bullet-opening uniformity

Pure function, ~50µs on typical posting length.

## Testing

```bash
make test    # uv run pytest
```

Integration tests spin up a PostgreSQL 18 container via
`testcontainers-python` and apply the bundled schema once per session.
Per-test isolation is via TRUNCATE — the container restart cost would
otherwise dominate runtime.

See `tests/test_e2e_pipeline.py` for a realistic end-to-end walk:
ingest LinkedIn + Bayt + Greenhouse postings of the same role, resolve
the company, cluster them, link granular skills, run AI detection,
recompute the verdict, and search the cluster from multiple angles
(English exact, synonym, typo, Arabic cross-language).

---

## Daily ops (the `make cycle` workflow)

Once the schema is applied and `.env` carries `JCDB_DSN`, the day-to-day
operation is three commands; everything else is composition.

```bash
make cycle          # daily — discover-ats → crawl-all → intelligence
make cycle-light    # nightly — skip discovery for a faster crawl+enrich
make cycle-heavy    # weekly  — refresh + validate proxy pool, then full cycle
```

Every step inside is idempotent. Safe to interrupt and re-run; safe to run
twice in a row.

### What `cycle` actually does

| Stage              | Purpose                                                                                                           |
| ---                | ---                                                                                                               |
| `discover-ats`     | Probe every seeded company for Greenhouse / Lever / Workable / SuccessFactors boards. New tenants land in `company_source_profiles` so the next ATS crawler picks them up automatically. |
| `crawl-all`        | Run every implemented crawler (Bayt, Greenhouse, Wuzzuf, Workable, …). Postings dedupe on `source + external_id`, so re-runs only insert genuinely new rows. |
| `intelligence`     | Skill extraction → salary / experience / education recovery from free text → city backfill (alias-aware) → HTML-entity title cleanup → cross-source dedup + cluster merging. All idempotent. |

### Inspect what landed

```bash
make data-stats           # cluster totals + per-source counts + coverage %
make data-stats-riyadh    # last-30-days Riyadh postings, sorted by title
```

### Override the defaults per-run

| Env var                      | Default | Effect                                  |
| ---                          | ---     | ---                                     |
| `JC_LOOKBACK_DAYS`           | 30      | Window the crawler filters to           |
| `JC_BAYT_MAX_PAGES`          | 40      | Pages per Bayt search query             |
| `JC_BAYT_QUERIES`            | (curated 18-keyword set) | CSV — override the default fan-out |
| `JC_GREENHOUSE_BOARDS`       | (3 verified) | CSV — additional Greenhouse slugs |
| `JC_WORKABLE_BOARDS`         | (3 verified) | CSV — additional Workable slugs   |
| `JC_FETCH_TIMEOUT_S`         | 20      | Per-request timeout (seconds)           |
| `JC_FETCH_MAX_CONCURRENCY`   | 3       | Parallel detail fetches per crawler     |

### Proxy pool (for LinkedIn / Naukrigulf)

```bash
make proxies-refresh        # pull fresh lists from monosans/proxifly/TheSpeedX
make proxies-validate       # probe each, blacklist the dead
make proxies-stats          # current alive/blacklisted/success-rate
```

`pick()` automatically prefers proxies with proven prior successes — so
the more `proxies-validate` you run, the curated set converges.

### Phase-3 sources (bot-hostile)

LinkedIn / Indeed / Glassdoor require residential proxies to be reliable.
The local free-pool path can connect via TLS impersonation but typically
gets IP-throttled within a handful of pages. These crawlers stay in the
registry; expect ~0 yield unless you wire in residential routing.

### Per-source convenience targets

If you only want to refresh one source:

```bash
make crawl-bayt
make crawl-greenhouse
make crawl-workable
make crawl-wuzzuf
make intelligence            # always cheap to re-run
```

`make crawl-list` shows every registered slug (✓ = implemented, · = stub).
