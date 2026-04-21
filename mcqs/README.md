# mcqs

Offline multiple-choice question bank generator + API, built over
[`vrtx-ai/docs-bundle`](/home/omar/workspace/vrtx-ai/docs-bundle).

Every top-level subject directory under `docs-bundle/` (java25, kubernetes,
sama, spring-boot-4, …) becomes a row in `subjects`, is chunked into
`doc_chunks`, and fed to Claude in batches to produce **8-option** MCQs in
three styles:

| Type | What it tests |
|---|---|
| `knowledge` | Literal recall — facts, flags, defaults, versions, commands |
| `analytical` | Why / trade-offs / how components interact |
| `problem_solving` | Scenario → best documented action |

A single **round** floors at ≥100 questions per `(subject, type)`; later
rounds layer on more without replacing earlier ones. The runtime loop plans
and drains rounds continuously so coverage compounds indefinitely.

The API lives at [`api.omarss.net/v1/mcq`](https://api.omarss.net/v1/mcq/docs)
behind the same `X-Api-Key` pattern as
[`gplaces_parser`](../gplaces_parser) — a single shared secret compared with
`hmac.compare_digest`. Options are shuffled and re-lettered on every
retrieval so no two requests for the same question return the same order.

---

## Contents

- [Architecture](#architecture)
- [Repo layout](#repo-layout)
- [Quickstart](#quickstart)
- [Schema](#schema)
- [API reference](#api-reference)
- [CLI reference](#cli-reference)
- [Generation internals](#generation-internals)
- [Rounds, concurrency, resumability](#rounds-concurrency-resumability)
- [Deployment](#deployment)
- [Operations](#operations)
- [Troubleshooting](#troubleshooting)
- [Known caveats](#known-caveats)

---

## Architecture

```
 ┌────────────────────────────────────────────────────────────────┐
 │                          docs-bundle/                          │
 │  java25/  kubernetes/  sama/  nginx/  spring-boot-4/  …  (46)  │
 └────────────────────────────────────────────────────────────────┘
                             │ mcqs ingest
                             ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  Postgres · subjects · source_docs · doc_chunks · topics       │
 │            · rounds · questions · question_options             │
 │            · question_topics · generation_jobs · api_usage     │
 └────────────────────────────────────────────────────────────────┘
                             │ mcqs generate  (resumable worker)
                             │     └──▶ subprocess: claude -p \
                             │              --output-format json \
                             │              --json-schema {…} \
                             │              --append-system-prompt …
                             ▼
 ┌────────────────────────────────────────────────────────────────┐
 │                        FastAPI /v1/mcq                         │
 │   /health  /subjects  /topics  /questions  /quiz               │
 │                  · X-Api-Key (HMAC compare)                    │
 │                  · options shuffled per-request                │
 │                  · random question order by default            │
 └────────────────────────────────────────────────────────────────┘
                             │
                             ▼
 host nginx (api.omarss.net) ──▶ NodePort 30802 (k3s) ──▶ pod
```

**Key design choices**

- **Offline generation.** All LLM work happens via `mcqs generate` (a
  resumable worker). The API is read-only against Postgres — it never
  calls out to Claude.
- **No API key for generation.** The worker shells out to the `claude`
  CLI, piggybacking on the user's Claude Code login. The
  `--json-schema` flag forces structured output so malformed replies
  are rejected by the CLI before they ever reach Python.
- **8 options per question.** 1 correct, 7 distractors. Options are
  stored in a stable A–H order at write time and shuffled + relettered
  on every retrieval, so the LLM's positional bias never leaks to
  consumers.
- **Dedup via `stem_hash`.** `SHA-256(normalize(stem))` is `UNIQUE` on
  `questions`, so the generator can retry safely and later rounds skip
  questions already in the bank.

---

## Repo layout

```
mcqs/
├── Makefile                  # install · db-create · migrate · ingest ·
│                             # plan-round · generate · status · serve ·
│                             # image-build · release · deploy · deploy-nginx
├── pyproject.toml            # python>=3.12 · fastapi · psycopg · typer ·
│                             # tiktoken · uvicorn · alembic
├── Dockerfile                # python:3.12-slim, UID 10001, API only
├── .env.example              # DATABASE_URL · MCQS_API_KEY · CLAUDE_CLI ·
│                             # CLAUDE_MODEL · DOCS_BUNDLE_ROOT · tuning
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 0001_initial.py         # 11 tables + 2 enums
│       └── 0002_eight_options.py   # widen letter CHECK A→D to A→H
├── scripts/
│   ├── bump-version.sh       # conventional-commit-driven version bump
│   ├── changelog.sh          # commit subjects since last mcqs/vX tag
│   └── run-forever.sh        # drain → plan next round → loop (background)
└── src/mcqs/
    ├── cli.py                # typer entry: serve/ingest/plan-round/generate/status
    ├── config.py             # pydantic-settings reading .env
    ├── db.py                 # psycopg pool, atexit-safe close
    ├── subjects.py           # discover top-level dirs under docs-bundle
    ├── chunker.py            # markdown-aware + HTML-stripping + token windows
    ├── ingest.py             # walk → hash → chunk → upsert
    ├── prompts.py            # SYSTEM + per-type rubrics + JSON schema
    ├── generate.py           # claim job → call claude → validate → persist
    └── api/
        ├── main.py           # FastAPI factory + uvicorn entry
        ├── deps.py           # require_api_key (HMAC constant-time)
        ├── routes.py         # /v1/mcq/*
        ├── queries.py        # SQL helpers
        ├── schemas.py        # pydantic response models
        └── usage.py          # per-key per-endpoint daily counter middleware
```

Infra lives under `../homelab/`:

```
homelab/
├── apps/api-mcqs/
│   ├── namespace.yaml
│   ├── deployment.yaml            # UID 10001 · readonly FS · probes
│   ├── service.yaml               # NodePort 30802
│   └── secret.template.yaml.tmpl  # template — .tmpl suffix keeps it
│                                  # out of the `kubectl apply -f <dir>` glob
└── nginx/
    └── api.omarss.net.conf        # adds `location /v1/mcq { proxy_pass … }`
```

---

## Quickstart

### 1. Prerequisites

- Ubuntu (native), Python ≥3.12, Postgres ≥16, Docker/podman, k3s
- Claude Code CLI on `$PATH`, logged in (`claude --help` works)
- The docs corpus exists at `DOCS_BUNDLE_ROOT`
  (default `/home/omar/workspace/vrtx-ai/docs-bundle`)

### 2. Local setup

```bash
# venv + editable install
make install

# create local Postgres role+db (needs sudo once)
make db-create

# env
cp .env.example .env
# → .env is fine as-is for local dev; fill MCQS_API_KEY if you plan to hit /serve

# schema
make migrate
```

### 3. Populate the bank

```bash
# walk docs-bundle → subjects / source_docs / doc_chunks
make ingest

# open round 1 + queue pending jobs (1 per subject × type, target=100)
.venv/bin/mcqs plan-round --target 100

# drain them (resumable; SIGINT is safe)
make generate

# watch progress
make status
```

Or let the forever-loop do rounds 1, 2, 3, … without supervision:

```bash
nohup bash scripts/run-forever.sh > /tmp/mcqs-gen.log 2>&1 &
tail -f /tmp/mcqs-gen.log
```

### 4. Serve the API locally

```bash
# MCQS_API_KEY must be set — generate once with: openssl rand -hex 32
make serve
# → http://127.0.0.1:8000/v1/mcq/docs
```

---

## Schema

All tables under the `mcqs` database, owner `mcqs`.

| Table | Rows | Why |
|---|---|---|
| `subjects` | 1 per top-level docs-bundle dir | Ingestion scope |
| `source_docs` | 1 per file | Hash-based idempotency |
| `doc_chunks` | 1 per ~1k-token window | Context for the LLM |
| `topics` | emerges from LLM tags | `UNIQUE(subject_slug, slug)` |
| `rounds` | 1 per generation round | Monotonic `number` |
| `questions` | 1 per MCQ | `stem_hash UNIQUE` dedupes |
| `question_options` | 8 per question | A–H letters, `is_correct` bool |
| `question_topics` | many-to-many | A question can span topics |
| `generation_jobs` | 1 per `(subject, round, type)` | Resumable queue |
| `api_usage` | 1 per `(key_prefix, endpoint, status, day)` | Per-key rate telemetry |

Enums:

- `question_type` ∈ `knowledge | analytical | problem_solving`
- `job_status` ∈ `pending | in_progress | done | failed`

Full DDL is a single Alembic migration — see
[`migrations/versions/0001_initial.py`](migrations/versions/0001_initial.py)
and [`0002_eight_options.py`](migrations/versions/0002_eight_options.py).

---

## API reference

Base: `https://api.omarss.net/v1/mcq` (or `http://127.0.0.1:8000/v1/mcq`
when running locally). Every data endpoint requires header
`X-Api-Key: <MCQS_API_KEY>`. `health` is public.

### `GET /v1/mcq/health` — public

Round-trip DB probe + corpus counts.

```bash
curl -s https://api.omarss.net/v1/mcq/health
# {"status":"ok","subjects":43,"questions":1710}
```

### `GET /v1/mcq/subjects` — list subjects

Per-subject breakdown of question counts by type and how many rounds are
present.

```json
{
  "subjects": [
    {
      "slug": "apple-pay",
      "title": "Apple Pay",
      "description": null,
      "total_questions": 330,
      "counts_by_type": {"knowledge":110, "analytical":110, "problem_solving":110},
      "rounds_covered": 2
    }
  ]
}
```

### `GET /v1/mcq/topics?subject=<slug>`

Topics extracted from the LLM's tags for questions within a subject,
sorted by frequency.

```json
{
  "subject": "pnpm",
  "topics": [
    {"slug":"workspace", "title":"workspace", "question_count":42},
    {"slug":"dependency-resolution", "title":"dependency-resolution", "question_count":37}
  ]
}
```

### `GET /v1/mcq/questions`

Paginated listing. Random order by default — acceptable caveat: two
requests with the same filter hand back different pages. Use
`/questions/{id}` for stable addressing.

Query params (all optional):

| Param | Type | Notes |
|---|---|---|
| `subject` | string | subject slug |
| `type` | enum | `knowledge` / `analytical` / `problem_solving` |
| `topic` | string | topic slug within subject |
| `difficulty` | 1..5 | |
| `round` | int ≥1 | |
| `limit` | int ≥1 | capped at `API_MAX_LIMIT` (default 100) |
| `offset` | 0..10_000 | |

Response:

```json
{
  "questions": [
    {
      "id": 1661,
      "subject": "argocd",
      "type": "knowledge",
      "round": 2,
      "difficulty": 1,
      "stem": "…",
      "options": [
        {"letter":"A","text":"argocd-api-server","is_correct":false},
        {"letter":"B","text":"argo-server","is_correct":true},
        …
      ],
      "explanation": "…",
      "topics": ["cli","repo-server"],
      "created_at": "2026-04-21T02:11:07.413Z"
    }
  ],
  "pagination": {"limit":25, "offset":0, "has_more":true}
}
```

### `GET /v1/mcq/questions/{id}`

Single question, full payload including `is_correct` on every option
and the `explanation`. Stable across repeated calls except for option
order.

### `GET /v1/mcq/quiz?subject=<slug>&count=10&type=<type>`

Random sample for a quiz flow. **The response strips `is_correct` and
`explanation`** — fetch `/questions/{id}` once the user has chosen to
reveal the answer.

```json
{
  "subject": "pnpm",
  "type": null,
  "questions": [
    {
      "id": 42,
      "stem": "…",
      "options": [
        {"letter":"A","text":"…","is_correct": null},
        {"letter":"B","text":"…","is_correct": null}
      ],
      "explanation": null,
      …
    }
  ]
}
```

### OpenAPI

Interactive docs:
[`https://api.omarss.net/v1/mcq/docs`](https://api.omarss.net/v1/mcq/docs)
· ReDoc at `/v1/mcq/redoc` · spec JSON at `/v1/mcq/openapi.json`.

### Errors

All errors share one envelope:

```json
{"error": "string"}
```

| Code | When |
|---|---|
| `400` | invalid query (e.g. `type=bogus`) |
| `401` | missing or wrong `X-Api-Key` |
| `404` | unknown question id |
| `500` | DB or upstream failure |

---

## CLI reference

All CLI commands read `.env`.

| Command | What |
|---|---|
| `mcqs serve` | Start the FastAPI service (requires `MCQS_API_KEY`) |
| `mcqs ingest [--subject <slug>]` | Walk docs-bundle, persist chunks. Idempotent on `content_hash` |
| `mcqs plan-round [--target N] [--notes "..."]` | Open a new `rounds` row + queue pending `generation_jobs`. Default target from `MCQS_PER_TYPE_TARGET` (100) |
| `mcqs generate [--subject] [--type] [--limit-jobs]` | Resumable worker — claim pending job → `claude -p` → validate → persist. Safe to run in multiple terminals |
| `mcqs status` | Round × subject × type progress table |

Makefile aliases: `make ingest`, `make plan-round [n=100]`,
`make generate`, `make status`, `make serve`.

---

## Generation internals

### Prompting

[`src/mcqs/prompts.py`](src/mcqs/prompts.py) ships:

1. A single **system prompt** specifying the JSON schema, the
   "8 options / 1 correct / never reference letter positions in
   explanations" contract, and anti-hallucination rules.
2. Three **rubrics** (one per `question_type`) layered on top of a
   shared user template.
3. A **JSON Schema** (`prompts.json_schema(count)`) passed to
   `claude -p --json-schema`. Anthropic requires the top-level schema
   to be an `object`, so the array of questions is wrapped in
   `{"questions": [...]}` and unwrapped after the call.

Each batch prompt carries:

- Subject title + slug
- Target count N
- Rubric for the type
- Up to 30 most-recent stems for that `(subject, type)` — dedup hint
  the LLM uses to avoid near-duplicate questions
- Up to `CHUNK_BUDGET_TOKENS` (6000) worth of chunks, preferring
  un-used ones first (`uses ASC, random()`)

### Worker flow

```
 ┌─────────────────────────────────────────────────────────────────┐
 │  SELECT … FOR UPDATE SKIP LOCKED  (claim a pending job)         │
 └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                  pick chunks (un-used first) + last-30 stems
                                │
                                ▼
                render_user_prompt(subject, type, N, chunks, stems)
                                │
                                ▼
  subprocess.run([claude, -p, --output-format json, --json-schema, …])
                                │                  (stdin = user prompt)
                                ▼
                     envelope["structured_output"]["questions"]
                                │
                                ▼
              validate each item (shape, chunk-id sanity, stem_hash)
                                │
                                ▼
            INSERT questions / question_options / question_topics
                                │
                                ▼
                UPDATE generation_jobs SET produced_count += n
                                │
                         target reached?
                        /              \
                      yes                no
                       │                  │
                       ▼                  └─► next batch
              SET status='done'
```

### Validation

Dropped per-item (batch continues):

- Options not length 8, any empty string
- `correct_index` outside 0–7
- Empty stem / explanation / missing difficulty / missing topics
- Empty `source_chunk_ids` after dropping ids the LLM hallucinated
  (chunk ids not in the batch's context)
- Stem hash collision with an existing question — silent dedup

Aborts a job (marks `failed` with `last_error` recorded):

- 3 consecutive batches that produce **0** new writes (dedup
  exhaustion for this subject/type at the current chunk coverage)
- Claude CLI timeout (`CLAUDE_TIMEOUT_SEC = 600`) or non-zero exit
- DB integrity error other than dedup

### Option shuffling on retrieval

Stored order (A→H) reflects the LLM's emission, which has positional
bias (the correct answer tends to cluster at low indices). The API
re-shuffles and re-letters on every request inside
[`_row_to_question`](src/mcqs/api/routes.py), so every `/questions`
or `/quiz` hit is a fresh permutation.

---

## Rounds, concurrency, resumability

### Rounds compound

`mcqs plan-round` inserts one `generation_jobs` row per
`(subject, round, type)`. Questions from earlier rounds stay in the
bank — later rounds **add** ≥N more. After three rounds at target=100,
each subject has ≥300 per type (subject to dedup).

`scripts/run-forever.sh` drains the current round, re-runs
`plan-round`, and loops. Stop it with `pkill -f run-forever.sh`.

### Safe to run many workers

Each job claim uses `SELECT … FOR UPDATE SKIP LOCKED`, so multiple
`mcqs generate` terminals (or containers) never pick the same row.
The cross-question `stem_hash UNIQUE` handles race dedup.

### Crashes are safe

A crashed worker leaves the job `in_progress`. The next worker through
`run_worker` calls `_requeue_stale` which resets every `in_progress`
job with `started_at > 15 min old` back to `pending`. Questions the
crashed worker wrote stay in — produced_count may drift under target;
when it's re-claimed, the worker fills the remainder.

### Idempotent ingest

`source_docs.content_hash` is `SHA-256(raw_bytes)`. Re-running
`mcqs ingest` after upstream docs change re-chunks only the files
whose hash moved. Files removed upstream stay in the DB (the
generator picks from whatever chunks exist — stale chunks are
harmless).

---

## Deployment

`api.omarss.net/v1/mcq` is live on the homelab k3s cluster. The bank
is populated by the host-side generator running against the local
Postgres; the pod only serves reads.

### One-time bootstrap

```bash
# 1. allow k3s pods (10.42.0.0/16) to reach host Postgres
sudo sh -c 'echo "host mcqs mcqs 10.42.0.0/16 scram-sha-256" >> /etc/postgresql/$(ls /etc/postgresql/)/main/pg_hba.conf'
sudo systemctl reload postgresql

# 2. namespace + secret (MCQS_API_KEY is independent of GPLACES_API_KEY)
openssl rand -hex 32 > /tmp/mcqs-k
sudo k3s kubectl create namespace api-mcqs --dry-run=client -o yaml | sudo k3s kubectl apply -f -
sudo k3s kubectl -n api-mcqs create secret generic api-mcqs-secrets \
  --from-literal=MCQS_API_KEY="$(cat /tmp/mcqs-k)" \
  --from-literal=DATABASE_URL="postgresql://mcqs:mcqs@10.42.0.1:5432/mcqs" \
  --dry-run=client -o yaml | sudo k3s kubectl apply -f -

# 3. manifests
sudo k3s kubectl apply -f ../homelab/apps/api-mcqs/

# 4. image
make image-build
docker save mcqs/api:latest -o /tmp/mcqs-api.tar
sudo k3s ctr images import /tmp/mcqs-api.tar

# 5. roll out
sudo k3s kubectl -n api-mcqs rollout restart deployment/api-mcqs
sudo k3s kubectl -n api-mcqs rollout status  deployment/api-mcqs --timeout=120s

# 6. nginx vhost + TLS
make deploy-nginx
sudo certbot --nginx -d api.omarss.net
```

### Releases (routine)

`make release` runs the whole thing: bump → commit → tag → build →
image save → deploy → push. Aborts on a dirty tree.

### Code-only deploy (no image change)

`make deploy TAG=<tag>` re-imports `/tmp/mcqs-api.tar` and rolls the
deployment. Use after a manual `docker build`.

### ⚠ Nginx footgun

`api.omarss.net.conf` is the shared vhost for both `api-places` and
`api-mcqs`. Every `make deploy-nginx` clobbers certbot's injected 443
listener — re-run `sudo certbot --nginx -d api.omarss.net` afterward
(it reuses the cached cert, no Let's Encrypt API call).

### ⚠ Secret template footgun

`homelab/apps/api-mcqs/secret.template.yaml.tmpl` has the `.tmpl`
suffix on purpose: `kubectl apply -f <dir>/` otherwise clobbers the
real runtime secret with `REPLACE_ME` placeholders. Don't rename it
back to `.yaml`.

---

## Operations

### Watch progress

```bash
# live log from the forever-loop
tail -f /tmp/mcqs-gen.log

# tabular status via CLI
make status

# per-subject counts
psql "$DATABASE_URL" -c "SELECT subject_slug, question_type, COUNT(*) \
                         FROM questions GROUP BY 1,2 ORDER BY 1,2;"

# per-pod logs
kubectl -n api-mcqs logs deploy/api-mcqs --tail=100 -f
```

### Start / stop the generator

```bash
# start (background, survives the shell exiting)
nohup bash scripts/run-forever.sh > /tmp/mcqs-gen.log 2>&1 &

# stop
pkill -f run-forever.sh

# stop any in-flight claude batch too (rare)
pkill -f 'claude --print'
```

### Force a new round manually

```bash
.venv/bin/mcqs plan-round --target 150 --notes "manual deep-dive round"
.venv/bin/mcqs generate                                    # drain it
```

### Retry failed jobs

```sql
UPDATE generation_jobs
   SET status='pending', last_error=NULL, started_at=NULL, finished_at=NULL
 WHERE status='failed';
```

### Per-key usage

```sql
SELECT day, endpoint, status_bucket, count
FROM api_usage ORDER BY day DESC, count DESC LIMIT 20;
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `POSTGRES password authentication failed for user "mcqs"` in pod logs | Secret was overwritten by the template on `kubectl apply -f <dir>/` | Re-create the secret with `--from-literal=…`; the template has been renamed to `.yaml.tmpl` in git but check you're not applying it |
| `claude exit 1: Error: Input must be provided…` | Prompt reached claude CLI as empty (piped but got consumed) | Worker now sends via stdin — ensure `claude` CLI version is current |
| `tools.N.custom.input_schema.type: Input should be 'object'` | JSON schema top-level isn't an object | `prompts.json_schema()` already wraps in `{questions: [...]}` — don't pass an array schema directly |
| Pod stuck in CrashLoopBackOff on readiness probe | DB unreachable — pg_hba missing `10.42.0.0/16` line, or password in secret wrong | `kubectl logs` the pod; re-check pg_hba + reload Postgres |
| 3 consecutive zero-write batches → job failed | Dedup exhausted for this `(subject, type)` at the current chunk coverage | Skip it — later rounds with different chunks will produce new questions |
| `/quiz` returns `is_correct` populated | Bug — should be `null` in `/quiz`. File an issue; `_row_to_question(hide_answer=True)` is the mechanism |
| Duplicate questions slip through | Ingest changed the source text → `stem_hash` collides less aggressively | Not a correctness bug; dedup is best-effort |

### Diagnostic one-liners

```bash
# is the pod actually reaching Postgres?
kubectl -n api-mcqs exec deploy/api-mcqs -- python -c "
import os, psycopg
with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5) as c:
    print('ok', c.execute('SELECT count(*) FROM questions').fetchone())"

# raw secret value (password redacted)
kubectl -n api-mcqs get secret api-mcqs-secrets \
  -o jsonpath='{.data.DATABASE_URL}' | base64 -d | sed 's/mcqs:[^@]*@/mcqs:<pw>@/'

# certbot-injected TLS listener still present?
sudo grep -A3 'listen 443' /etc/nginx/sites-available/api.omarss.net.conf
```

---

## Known caveats

- **Topic slugs are whatever the LLM emits.** Similar concepts may
  end up as different slugs (`rbac` vs `role-based-access-control`).
  The `topics` table doesn't coalesce them; a future pass could add
  a canonical-slug mapping.
- **`source_chunk_ids` is advisory.** Re-ingesting a file deletes its
  old chunks and inserts new ones — existing question rows keep their
  (now-dangling) chunk id references. Not a correctness issue for the
  API; the generator's `_pick_chunks` still works off whatever chunks
  exist.
- **Random pagination.** `GET /v1/mcq/questions` returns a fresh
  random order each call. A client paginating through "all questions"
  will see repeats. Use `/v1/mcq/questions/{id}` for stable
  addressing, or filter by `(round, subject, type)` + fixed `id`
  order client-side if you need determinism — endpoint option tbd.
- **No observability yet.** No Prometheus metrics or structured logs
  beyond `api_usage`. Quality eval of generated MCQs is manual.
- **One-way migrations.** `downgrade()` is implemented but never
  exercised in prod. Don't rely on it.

---

## Related

- [`gplaces_parser`](../gplaces_parser) — sibling service on the same
  `api.omarss.net` host, same `X-Api-Key` auth pattern, different
  NodePort (30801)
- [`vrtx-ai/docs-bundle`](/home/omar/workspace/vrtx-ai/docs-bundle) —
  source corpus
- [`../homelab/`](../homelab) — k3s + nginx gitops root
