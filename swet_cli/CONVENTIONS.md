# Engineering Conventions

This document defines the engineering standard for this repository.

It is intentionally opinionated.

It is based on the current stack in this repo:

- Python 3.12
- Typer CLI apps
- FastAPI API services
- Pydantic 2
- SQLite today, with code that should remain portable to a more serious database later
- Pytest, Ruff, mypy
- SvelteKit 2 + Svelte 5
- TypeScript strict mode
- Vite 7
- Tailwind CSS 4
- `pnpm` for the web app

This document is not a description of the current codebase. It is the standard the codebase should move toward. If an existing pattern conflicts with this document, prefer this document unless there is a documented exception.

## Non-Negotiables

- Keep transport layers thin.
- Keep domain logic typed and testable.
- Prefer explicitness over convenience.
- Prefer simple architecture over clever abstraction.
- No hidden state.
- No hidden I/O.
- No untyped boundaries.
- No copy-pasted business logic across CLI, API, Slack, Telegram, WhatsApp, or web.
- No silent failures.
- No broad exceptions without a reason.
- No leaking secrets, tokens, or sensitive data into logs, HTML, local storage, screenshots, or tests.

## Golden Rules

1. Put business logic in shared Python services or domain modules, not in handlers, routers, route files, or UI components.
2. Make invalid states unrepresentable with types and schemas.
3. Validate all external input at the edge.
4. Keep I/O at the edge and pure logic in the middle.
5. Optimize for maintainability before micro-optimizing performance.
6. If a piece of logic is hard to test, it is probably in the wrong place.
7. If a function needs a comment to explain basic mechanics or confusing control flow, rewrite it. Comments that explain domain rules, thresholds, invariants, or why a branch exists are good.
8. If two layers know too much about each other, the boundary is wrong.

## Reading The Rules

The document uses three practical categories:

- Default: the standard starting point for new code in this repo.
- Scale-up path: the pattern to adopt when complexity, traffic, or risk grows.
- Accepted exception: allowed when the simpler option is a better fit and the tradeoff is explicit.

## Repository-Level Conventions

### Do

- Keep shared logic in modules that are independent of the transport surface.
- Treat CLI, HTTP, Slack, Telegram, and WhatsApp as adapters around the same core behavior.
- Keep data contracts explicit.
- Prefer one obvious place for each responsibility.

### Do Not

- Reimplement the same grading, question generation, auth, or formatting logic in each entrypoint.
- Put persistence logic directly in UI code or transport handlers.
- Use convenience imports that hide ownership.
- Introduce framework-specific code into reusable domain modules.

### Bad

```python
# Telegram handler contains business rules
def handle_answer(update):
    score = grade_answer(update.message.text)
    level = adjust_difficulty(score)
    save_attempt(score, level)
```

### Right

```python
# Handler adapts transport to service call
def handle_answer(update):
    result = assessment_service.grade_answer(
        user_id=str(update.effective_user.id),
        answer_text=update.message.text,
    )
    send_grade_message(update, result)
```

## Architecture

### Preferred Shape

- Domain layer: pure rules, scoring, selection logic, transforms.
- Service layer: orchestrates repositories, LLM calls, auth, and side effects.
- Repository layer: persistence only.
- Transport layer: CLI commands, FastAPI routers, bot handlers, Svelte UI routes and components.

### Rules

- Domain code must not know whether it was called from CLI, API, or a bot.
- Repositories must not contain business decisions.
- Routers and handlers must not assemble SQL.
- UI components must not encode API rules or auth flows.

### Bad

```python
@router.post("/questions/generate")
def generate(req: GenerateRequest):
    prefs = db.execute("SELECT * FROM preferences").fetchone()
    difficulty = 5 if prefs["role"] == "senior" else 2
    prompt = f"Generate {difficulty} question"
    raw = llm.generate(prompt)
    db.execute("INSERT INTO questions ...", ...)
    return raw
```

### Right

```python
@router.post("/questions/generate", response_model=list[QuestionResponse])
def generate(req: GenerateRequest, user: CurrentUser) -> list[QuestionResponse]:
    return question_service.generate_questions(user_id=user.id, request=req)
```

## Opinionated Architecture Decisions

These are deliberate defaults for this repo. They are not suggestions.

### Default Decisions

- The default backend architecture is a modular monolith.
- Shared Python domain and service code is the product. CLI, API, Slack, Telegram, WhatsApp, and web are adapters around it.
- FastAPI is the only approved framework for new HTTP APIs and webhooks.
- Flask is legacy-only in this repo. Do not add new Flask apps unless a vendor integration makes it unavoidable and the exception is documented.
- The web app remains a static-deployed SPA by default. Reintroduce SSR only for a specific reason such as SEO, server-only secrets, or server-rendered personalization that cannot be solved another way.
- SQLite is acceptable only for local development, demos, and low-scale single-writer deployments.
- Postgres is the default upgrade target once concurrency, scale, reliability, or operational needs exceed SQLite's comfort zone.
- The API layer must stay stateless. Per-user or per-request state belongs in the database, cache, signed cookies, or explicit request context, never in process globals.
- OpenAPI is the contract between backend and frontend.
- New Python I/O code should be designed so it can move from SQLite to Postgres and from in-process calls to queued jobs without rewriting the domain layer.

### Scale-Up Triggers

Move from SQLite to Postgres when any of these are true:

- More than one app instance writes to the database.
- Background workers and request handlers both write to the same tables.
- You need online schema migrations, row-level locking, stronger concurrency guarantees, or reliable backup/restore.
- Database write contention, lock errors, or WAL management become operational concerns.

Introduce a queue or worker tier when any of these are true:

- A request path depends on slow or flaky providers such as LLMs, email, SMS, or chat APIs.
- The operation is retryable and does not need to complete inline.
- User-visible p95 latency exceeds the budget because of external calls.
- The same work may be retried or duplicated unless idempotency is enforced centrally.

Split a module into an independently deployable service only when:

- It has a clearly different scale profile.
- It has distinct operational ownership.
- It needs isolation for compliance or blast-radius reasons.
- The interface is already stable and explicit.
- "Team preference" or "future-proofing" is not a valid reason to create a new service.

### Approved Patterns

- Use a service layer for orchestration once a feature has real business rules, multiple side effects, or multiple entrypoints.
- Use a repository layer for persistence once queries, transactions, or storage reuse stop being trivial.
- Use explicit typed contracts between layers.
- Use background jobs for long-running or provider-bound work once inline execution stops meeting the latency or reliability budget.
- Use feature modules, not horizontal dumping grounds.
- Keep simple features simple when a thinner structure is still typed, readable, and testable.

### Rejected Patterns

- Microservices by default.
- Framework-driven business logic.
- Fat routers, fat handlers, or fat page components.
- Multiple competing ways to do the same thing.
- In-process cron or background threads inside web workers for business-critical jobs.

### Bad

```python
# New feature gets its own service because it might scale later
app = Flask(__name__)

@app.post("/grade")
def grade():
    ...
```

### Right

```python
# Same product, same domain layer, one backend architecture
router = APIRouter(prefix="/attempts", tags=["attempts"])

@router.post("/grade", response_model=GradeResponse)
def grade(req: AnswerRequest, user: CurrentUser) -> GradeResponse:
    return attempt_service.grade_answer(user_id=user.id, request=req)
```

## Naming And Layout

### Do

- Use singular, responsibility-based module names when possible.
- Name functions after behavior, not implementation details.
- Use `*_service.py`, `*_repository.py`, `*_schemas.py`, `*_types.ts`, `*.svelte.ts` only when the suffix adds real signal.
- Keep names stable and boring.

### Do Not

- Use `helpers.py`, `utils.py`, `misc.py`, `common.py`, or similarly vague names as a dumping ground. A focused `utils/` directory or small utility module is acceptable when the ownership is clear.
- Use vague names like `process`, `handle`, `manager`, or `data` unless the context makes them precise.

### Bad

```python
def do_it(data):
    ...
```

### Right

```python
def grade_attempt(answer_text: str, rubric: GradingRubric) -> GradeResult:
    ...
```

## Python Conventions

### Types

#### Do

- Type all public functions.
- Type all function returns.
- Use `str | None` rather than `Optional[str]`.
- Use `list[str]`, `dict[str, int]`, and `tuple[...]` builtins.
- Use `TypedDict`, `dataclass`, or Pydantic models when structure matters.
- Let mypy strict mode drive design, not just syntax.

#### Do Not

- Use `Any` in application code unless there is no practical alternative and the reason is documented.
- Return raw `dict` objects for important domain entities.
- Use `cast()` to silence bad design.

#### Bad

```python
def create_question(data):
    return {"id": "q1", "title": data["title"]}
```

#### Right

```python
class QuestionDraft(BaseModel):
    title: str
    body: str


def create_question(data: QuestionDraft) -> QuestionResponse:
    return QuestionResponse(id="q1", title=data.title, body=data.body)
```

### Functions

#### Do

- Keep functions focused on one job.
- Make dependencies explicit through parameters.
- Return values instead of mutating hidden global state.
- Prefer pure functions when possible.

#### Do Not

- Read environment variables directly inside arbitrary functions.
- Open files, call databases, and call LLMs from the same function that also contains business rules.
- Mutate module-level globals for request-specific behavior.

#### Bad

```python
def generate_and_save():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    prefs = load_prefs()
    question = llm.generate(api_key, prefs)
    save_question(question)
    return question
```

#### Right

```python
def generate_question(request: GenerateQuestionRequest, generator: QuestionGenerator) -> QuestionDraft:
    return generator.generate(request)


def create_question_for_user(
    user_id: str,
    request: GenerateQuestionRequest,
    generator: QuestionGenerator,
    repository: QuestionRepository,
) -> QuestionResponse:
    draft = generate_question(request, generator)
    return repository.save_for_user(user_id=user_id, draft=draft)
```

### Errors

#### Do

- Raise specific exceptions.
- Translate internal exceptions to user-facing HTTP or CLI errors at the edge.
- Fail loudly when invariants are broken.
- Include enough context for debugging without leaking secrets.

#### Do Not

- Catch `Exception` and continue.
- Return `None` for error cases that should be explicit.
- Swallow parsing or validation errors.

#### Bad

```python
try:
    result = provider.send(destination, code)
except Exception:
    return {"message": "something went wrong"}
```

#### Right

```python
try:
    provider.send(destination, code)
except ProviderTimeoutError as exc:
    raise HTTPException(status_code=503, detail="OTP provider unavailable") from exc
```

### Configuration

#### Do

- Read environment variables in one configuration module.
- Parse config into typed settings objects.
- Validate required config at startup.
- Allow safe development defaults for non-secret values.
- Separate development defaults from production secrets.

#### Do Not

- Scatter `os.getenv()` across the codebase.
- Hide default values inside random functions.
- Read configuration at import time when startup-time validation is enough.

#### Bad

```python
API_URL = os.getenv("API_URL", "http://localhost:8000")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
```

#### Right

```python
class ApiConfig(BaseModel):
    api_url: AnyHttpUrl = "http://localhost:8000"
    jwt_secret: SecretStr


def get_api_config() -> ApiConfig:
    return ApiConfig(
        api_url=os.environ.get("API_URL", "http://localhost:8000"),
        jwt_secret=os.environ["JWT_SECRET"],
    )
```

### Logging

#### Do

- Use the logging module.
- Emit structured logs where possible.
- Log identifiers, outcomes, durations, and retry counts.
- Redact tokens, OTPs, passwords, cookies, and PII.

#### Do Not

- Use `print()` in production code.
- Log full request bodies by default.
- Log secrets for debugging.

#### Bad

```python
print("refresh token:", refresh_token)
```

#### Right

```python
logger.info(
    "refresh token rotated",
    extra={"user_id": user_id, "token_id": token_id},
)
```

## Pydantic Conventions

### Do

- Use Pydantic models for all external input and output boundaries.
- Keep request models, response models, and internal domain models separate when their concerns differ.
- Use constrained fields and validators for actual invariants.
- Use `model_validate()` and `model_dump()` intentionally.

### Do Not

- Treat Pydantic as a generic bag of fields.
- Reuse the same model for database records, incoming requests, internal rules, and public responses if those shapes differ.
- Trust raw dicts from HTTP, JSON, SQLite, or LLMs.

### Bad

```python
class User(BaseModel):
    id: str
    email: str | None = None
    password_hash: str | None = None
    is_admin: bool = False
```

### Right

```python
class RegisterRequest(BaseModel):
    email: EmailStr | None = None
    mobile: str | None = None


class UserRecord(BaseModel):
    id: str
    email: EmailStr | None = None
    mobile: str | None = None
    password_hash: str | None = None


class UserResponse(BaseModel):
    id: str
    email: EmailStr | None = None
    mobile: str | None = None
```

## FastAPI Conventions

### Routers

#### Do

- Keep routers thin.
- Declare `response_model` explicitly.
- Use dependencies for auth, tracing, and shared cross-cutting concerns.
- Return typed models, not unstructured dicts.

#### Do Not

- Put SQL, prompt construction, or business policy in route functions.
- Make routers responsible for token rotation logic, retry policy, or adaptive scoring rules.
- Return inconsistent error shapes.

### Bad

```python
@router.post("/login")
def login(payload: dict):
    user = db.execute("SELECT * FROM users WHERE email = ?", (payload["email"],)).fetchone()
    if not user:
        return {"error": "bad credentials"}
    return {"token": create_token(user["id"])}
```

### Right

```python
@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, service: AuthServiceDep) -> TokenResponse:
    return service.login(req)
```

### HTTP Semantics

#### Do

- Use the correct status code.
- Use `201` for creation, `204` for no-body success, `400` for invalid input, `401` for unauthenticated, `403` for unauthorized, `404` for missing resources, `409` for conflicts, and `422` only when FastAPI validation semantics genuinely apply.
- Make idempotency explicit for retryable endpoints.

#### Do Not

- Return `200` for every outcome.
- Use `500` for expected business failures.
- Leak internal exception text to clients.

### Dependency Injection

#### Do

- Use FastAPI dependencies for per-request concerns.
- Keep dependencies deterministic and side-effect-light.

#### Do Not

- Hide heavy startup work inside request dependencies.
- Use global mutable singletons for request state.

## Database And Persistence Conventions

SQLite is acceptable for local and low-scale scenarios, but persistence code must be written so it can survive a future move to Postgres.

### Do

- Use one repository layer for database access.
- Use parameterized queries only.
- Keep schema migration concerns separate from request handling.
- Convert rows into typed models near the repository boundary.
- Make transactions explicit for multi-step writes.
- For disposable local SQLite databases, keep setup simple if the schema and recovery story are simple.

### Do Not

- Build SQL with string interpolation.
- Return raw `sqlite3.Row` objects to services or routers.
- Hide schema creation in every connection path in long-term production code.
- Encode multiple logical fields inside one untyped JSON blob unless there is a strong reason.

### Bad

```python
conn.execute(f"SELECT * FROM users WHERE email = '{email}'")
```

### Right

```python
row = conn.execute(
    "SELECT id, email, mobile FROM users WHERE email = ?",
    (email,),
).fetchone()
user = UserRecord.model_validate(dict(row)) if row else None
```

### Migration Rule

- Once the schema matters in production or in a multi-user deployment, use real migrations.
- Do not rely on `CREATE TABLE IF NOT EXISTS` as a migration strategy for production or multi-user databases.
- Never make destructive schema changes without a forward migration and a rollback plan.
- Accepted exception: for disposable local CLI SQLite databases, `CREATE TABLE IF NOT EXISTS` can be acceptable when recreation is cheap and backward compatibility is not a product requirement.

## Scalability And Performance Conventions

Scalability is not just about handling more traffic. It is about keeping the system predictable as traffic, features, and teams grow.

### Backend Scalability

#### Do

- Design every internet-facing endpoint to be stateless.
- Bound collection endpoints. Use `LIMIT` at minimum, and adopt cursor pagination once result sets or navigation patterns justify it.
- Add indexes for actual query patterns, not guesses.
- Make idempotency explicit for retryable writes.
- Bound concurrency against external providers.
- Add rate limits for auth, OTP, grading, question generation, and other abuse-prone endpoints.
- Use request IDs and user IDs in logs and traces.
- Keep hot paths free of unnecessary JSON parsing, prompt construction, and repeated database round-trips.
- Move slow provider calls to background jobs when they stop fitting the interactive latency budget.

#### Do Not

- Return entire history tables because the current dataset is small.
- Perform N+1 queries in request paths.
- Recompute expensive aggregates on every request if they can be precomputed or cached safely.
- Allow one user's expensive workflow to starve the whole process.

### Frontend Performance

#### Do

- Use route-level loading to avoid client-fetch waterfalls.
- Lazy-load heavy libraries such as syntax highlighting, code editors, or large charting bundles.
- Keep markdown rendering, syntax highlighting, and large JSON transforms off the critical path when possible.
- Use immutable asset hashing and aggressive cache headers for static assets.
- Keep bundle growth visible in reviews.

#### Do Not

- Eagerly import Shiki or other heavy libraries into the app shell.
- Fetch the same server data in parent and child routes.
- Keep large derived arrays reactive when they can be computed once per navigation or request.

### Performance Budgets

These are opinionated defaults. If we exceed them, treat that as a defect to be explained, not trivia.

- Auth and health endpoints: p95 under 300 ms excluding network transit.
- Normal API reads: p95 under 300 ms.
- Normal API writes: p95 under 500 ms.
- Interactive provider-backed actions: p95 under 8 seconds, otherwise convert them into asynchronous jobs with progress or polling.
- Initial authenticated app shell JavaScript: target under 250 KB gzipped before lazily loaded feature bundles.
- SQL in hot paths must use an index that matches the filter or sort pattern.

### Caching Rules

#### Do

- Cache only when there is a clear ownership and invalidation rule.
- Cache read-mostly reference data, derived stats, and provider results only when correctness is preserved.
- Prefer explicit TTLs and versioned keys.

#### Do Not

- Cache mutable user state without invalidation.
- Add a cache to compensate for inefficient query design.
- Share one giant process-global cache between unrelated concerns.

### Observability For Scale

#### Do

- Track request rate, error rate, latency percentiles, queue depth, retry counts, provider failures, and token refresh failures.
- Separate health checks from readiness checks once the app has external dependencies.
- Alert on saturation signals such as DB lock contention, queue backlog, and provider timeout spikes.

#### Do Not

- Discuss scale without metrics.
- Depend on ad hoc log-grepping as the main production debugging strategy.

### Bad

```python
@router.get("/history")
def history(user: CurrentUser):
    return repository.list_all_attempts_for_user(user.id)
```

### Default

```python
@router.get("/history", response_model=list[AttemptHistoryItem])
def history(user: CurrentUser, limit: int = 50) -> list[AttemptHistoryItem]:
    return attempt_service.list_recent_history(user_id=user.id, limit=limit)
```

### Scale-Up Path

```python
@router.get("/history", response_model=AttemptHistoryPage)
def history(user: CurrentUser, cursor: str | None = None, limit: int = 20) -> AttemptHistoryPage:
    return attempt_service.list_history(user_id=user.id, cursor=cursor, limit=limit)
```

## Auth And Security Conventions

### Tokens

#### Do

- Prefer secure, `HttpOnly`, `SameSite` cookies for browser auth when same-origin deployment is stable enough to support them cleanly.
- If using JWTs, keep access tokens short-lived.
- Rotate refresh tokens.
- Store refresh tokens server-side as hashes.
- Revoke tokens on logout and credential-sensitive events.
- Pin accepted JWT algorithms explicitly when decoding.
- Add CSRF protection for unsafe browser requests when auth uses cookies.
- If you intentionally use browser-readable refresh tokens in a small static SPA, treat it as an accepted exception with documented risk, short TTLs, CSP, strict sanitization, and explicit revocation behavior.

#### Do Not

- Treat browser-readable refresh tokens as the default pattern.
- Keep long-lived bearer tokens in browser-readable storage.
- Put secrets into frontend bundles.
- Allow wildcard CORS in production for authenticated APIs.
- Accept whatever JWT algorithm the token header asks for.

### Bad

```ts
localStorage.setItem('refresh_token', refreshToken);
```

### Preferred Default

```ts
// Browser never reads the refresh token.
// Backend sets it in a secure HttpOnly cookie.
await api.post('auth/login', { json: credentials });
```

### Accepted Exception

```ts
// Small static SPA with explicit risk acceptance.
// Keep TTLs short, keep CSP tight, and do not treat this as the long-term default.
localStorage.setItem('refresh_token', shortLivedRefreshToken);
```

### CORS And Origins

#### Do

- Allow only known production origins.
- Keep development and production CORS configuration separate.

#### Do Not

- Use `allow_origins=["*"]` in production with credentials.

### Browser And Frontend Security

#### Do

- Prefer secure, `HttpOnly`, `SameSite` cookies for browser sessions and refresh tokens when the deployment model supports them cleanly.
- Set a strict Content Security Policy in production.
- Set `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and a restrictive `Permissions-Policy`.
- Sanitize any HTML rendered from markdown or rich text.
- Treat every `{@html}` usage as a security-sensitive code review item.

#### Do Not

- Persist long-lived refresh tokens in `localStorage`, `sessionStorage`, or IndexedDB without an explicit exception and risk acceptance.
- Render raw markdown output directly.
- Assume framework escaping protects HTML injected via `{@html}`.

### Abuse Prevention

#### Do

- Rate-limit OTP send and verify endpoints by IP, user identifier, and destination.
- Expire OTPs quickly.
- Cap OTP verification attempts.
- Make refresh token rotation one-time-use.
- Add brute-force protection and temporary lockouts for repeated failures.
- Use generic messaging where possible to reduce account enumeration risk.

#### Do Not

- Allow unlimited OTP attempts.
- Expose whether a given email or phone definitely exists unless the product requires it and the risk is accepted.
- Keep long-lived refresh tokens active after logout or credential changes.

### Secret Management

#### Do

- Load secrets from environment or a secret manager at the edge of the app.
- Keep signing keys, provider keys, and webhook secrets out of the browser bundle.
- Rotate secrets deliberately and document the rotation path.
- Use separate secrets per environment.

#### Do Not

- Commit real secrets, tokens, or signed example credentials to the repo.
- Reuse one JWT secret across unrelated environments.
- Bake secrets into frontend config or static HTML.

### Markdown, HTML, And Content Rendering

#### Do

- Pass markdown through a parser and then through `DOMPurify` before rendering.
- Keep the sanitization step in one shared utility.
- Limit or explicitly review any feature that permits raw HTML, embedded iframes, or scriptable content.

#### Do Not

- Call `marked()` and pass the result straight to `{@html}`.
- Duplicate custom sanitization logic across components.
- Assume model-generated markdown is trusted.

### LLM And Prompt Security

#### Do

- Treat user prompts, retrieved content, and tool output as untrusted input.
- Validate every structured LLM response with a schema before use.
- Keep system prompts, secrets, and policy text separate from user-controlled input.
- Gate destructive or side-effecting actions with deterministic code, not model opinion.
- Record provider failures, retries, and malformed output for incident review.

#### Do Not

- Let the model decide authorization, entitlements, or whether a secret may be revealed.
- Execute code, SQL, shell commands, or HTML produced by the model without a separate trust boundary.
- Assume prompt injection is solved by wording alone.

### Webhooks And Provider Integrations

#### Do

- Verify webhook signatures.
- Enforce timestamp tolerance to prevent replay attacks.
- Make webhook handlers idempotent.
- Queue provider retries rather than blocking request threads.

#### Do Not

- Trust provider payloads without signature verification.
- Process the same webhook event twice without deduplication.

### Data Handling

#### Do

- Classify data: public, internal, sensitive, secret.
- Minimize storage of PII and model transcripts.
- Set retention rules for OTPs, tokens, and generated content.
- Redact secrets and PII from logs and traces.

#### Do Not

- Keep expired OTPs, revoked refresh tokens, or detailed provider payloads forever without reason.
- Store more personal data than the feature requires.

## API Contract Conventions

### Source Of Truth

- FastAPI schemas are the source of truth for API payloads.
- Frontend request and response types should be generated from OpenAPI when practical.
- If manual frontend types exist, they must mirror backend schemas exactly and be covered by contract tests.

### Naming

- Use `snake_case` on the wire for Python-facing payloads unless there is a clear, enforced translation boundary.
- If the frontend wants `camelCase`, translate once at the edge. Do not mix conventions randomly in payloads.

### Versioning

- Version breaking APIs deliberately.
- Do not break the web app, bots, and CLI silently with schema drift.

### Bad

```ts
export interface TokenResponse {
  accessToken: string;
  refresh_token: string;
}
```

### Right

```ts
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}
```

## CLI And Bot Conventions

### Do

- Treat CLI commands and bot handlers as thin adapters.
- Keep formatting separate from business logic.
- Parse external input early and normalize it once.
- Keep retries, backoff, and provider errors explicit.

### Do Not

- Put grading logic inside Slack block builders.
- Put persistence logic inside Telegram keyboard code.
- Duplicate parsing and validation rules between chat integrations.

### Bad

```python
def build_slack_response(payload: dict) -> dict:
    score = grade(payload["answer"])
    save_score(payload["user"], score)
    return {"text": f"Score: {score}"}
```

### Right

```python
def build_slack_response(result: GradeResult) -> dict:
    return slack_formatter.format_grade(result)
```

## Frontend Conventions

The web app is a SvelteKit app running in SPA mode. That matters.

### TypeScript

#### Do

- Keep `strict` mode on.
- Type all exported functions, store state, API responses, and component props.
- Prefer discriminated unions for UI state machines.
- Use `unknown` instead of `any` when parsing untrusted data.

#### Do Not

- Use `any` to bypass missing modeling work.
- Pass untyped API payloads through the component tree.
- Use non-null assertions to paper over lifecycle issues.

### Bad

```ts
let user: any;
user = await response.json();
```

### Right

```ts
const payload: unknown = await response.json();
const user = parseUserResponse(payload);
```

### Svelte 5

#### Do

- Use Svelte 5 runes deliberately for reactive local state.
- Keep component-local state local.
- Use shared stores only for cross-route or cross-feature state such as auth, app-level toasts, or current session context.
- Keep components small and focused.
- Move non-trivial logic into `$lib`.

#### Do Not

- Use a global store for every piece of page state.
- Put API orchestration, token logic, and data shaping directly inside markup-heavy components.
- Mix view rendering, mutation logic, and navigation concerns in one giant `.svelte` file.

### Bad

```svelte
<script lang="ts">
	let questions = $state([]);

	async function load() {
		const res = await fetch('/questions');
		questions = await res.json();
	}

	load();
</script>
```

### Right

```svelte
<script lang="ts">
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>
```

```ts
// +page.ts
import { listQuestions } from '$lib/api/questions';

export async function load() {
	return {
		questions: await listQuestions()
	};
}
```

### Routing And Data Loading

#### Do

- Use `+page.ts` and `+layout.ts` for route-level data that should participate in navigation.
- Keep data fetching in `$lib/api/*` modules.
- Use page `load` for initial route data.
- Use direct client-side API calls for user-triggered mutations.

#### Do Not

- Scatter raw `fetch` and `ky` calls across components.
- Duplicate endpoint URLs in many files.
- Depend on `+page.server.ts` patterns in a static SPA deployment.

### Component Design

#### Do

- Keep presentational components mostly stateless.
- Pass in typed data and callbacks.
- Split large pages into route orchestration plus smaller components.
- Keep formatting helpers in utility modules.

#### Do Not

- Create components that know about storage, routing, auth refresh, analytics, and API details all at once.
- Use components as hidden service locators.

## Frontend State Management

### Do

- Use local state first.
- Use route `load` for route-scoped data.
- Use shared stores for long-lived app state only.
- Keep derived state derived, not duplicated.

### Do Not

- Mirror server data into many stores without a cache strategy.
- Keep stale copies of the same entity in multiple places.
- Persist sensitive state in browser-readable storage.

### Bad

```ts
export const questions = createQuestionsStore();
export const dashboardQuestions = createQuestionsStore();
export const historyQuestions = createQuestionsStore();
```

### Right

```ts
// Route data owns route-scoped server state.
// Shared store owns app session state.
export const auth = createAuthStore();
```

## Styling And Tailwind Conventions

### Do

- Prefer semantic structure first, utility classes second.
- Use design tokens and CSS variables for color, spacing, radius, and typography decisions that repeat.
- Keep utility class lists readable.
- Extract repeated UI patterns into components.
- Build accessible focus states intentionally.

### Do Not

- Dump 40-class inline strings into every component when a component or class abstraction is clearer.
- Use arbitrary values everywhere.
- Encode business state only in color.

### Bad

```svelte
<button class="px-[13px] py-[7px] rounded-[11px] bg-[#1f6feb] text-white text-[13px] font-[650]">
	Save
</button>
```

### Right

```svelte
<button class="btn-primary">
	Save
</button>
```

```css
.btn-primary {
	@apply inline-flex items-center justify-center rounded-md px-4 py-2 font-medium;
}
```

## Accessibility Conventions

### Do

- Use semantic HTML first.
- Label every form control.
- Ensure keyboard access for every interaction.
- Keep visible focus styles.
- Announce async loading and error states where needed.

### Do Not

- Replace buttons with clickable `div`s.
- Remove focus outlines without adding a better replacement.
- Use color alone to convey validity, status, or grading.

### Bad

```svelte
<div on:click={submit}>Submit</div>
```

### Right

```svelte
<button type="button" on:click={submit}>Submit</button>
```

## API Client Conventions

### Do

- Centralize HTTP setup in one client module.
- Centralize retries, auth headers, and response parsing.
- Normalize error handling in one place.
- Keep endpoint modules small and typed.

### Do Not

- Create a new `ky` or `fetch` wrapper in each feature.
- Retry non-idempotent writes blindly.
- Hide token refresh behavior in random components.

### Bad

```ts
export async function getStats() {
	return fetch('/stats').then((r) => r.json());
}
```

### Right

```ts
export async function getStats(): Promise<StatsResponse[]> {
	return api.get('stats').json<StatsResponse[]>();
}
```

## Deprecated, Banned, And Legacy APIs

This section mixes two categories:

- Official upstream deprecations in the current stack.
- Project-level bans where we are standardizing on a stricter practice than the framework technically allows.

### Python Standard Library

#### Officially Deprecated Or Discouraged

- Do not use `datetime.utcnow()` or `datetime.utcfromtimestamp()`.
- Use aware UTC datetimes: `datetime.now(UTC)` and `datetime.fromtimestamp(ts, UTC)`.

### Bad

```python
issued_at = datetime.utcnow()
```

### Right

```python
issued_at = datetime.now(UTC)
```

### Project-Level Bans

- No new `logging.warn()`. Use `logging.warning()`.
- No new `eval()` or `exec()` for dynamic behavior in application code.
- No new `tempfile.mktemp()` or other insecure temporary-file patterns.

### Pydantic

#### Officially Deprecated In V2

- No new `parse_raw()` or `parse_file()`.
- No new `from_orm()`.
- No new V1-style method calls such as `parse_obj()` when `model_validate()` is the real API.
- No new V1 compatibility methods like `.dict()`, `.json()`, `.copy()`, or `.construct()` in new code; use `model_dump()`, `model_dump_json()`, `model_copy()`, and `model_construct()`.
- No new `@validator` or `@root_validator` in new models; use `@field_validator` and `@model_validator`.

### Bad

```python
payload = TokenResponse.parse_raw(raw_json)
data = payload.dict()
```

### Right

```python
payload = TokenResponse.model_validate_json(raw_json)
data = payload.model_dump()
```

### FastAPI

#### Officially Deprecated

- No new `@app.on_event("startup")` or `@app.on_event("shutdown")`.
- Use the `lifespan` parameter on the FastAPI app.

### Bad

```python
app = FastAPI()

@app.on_event("startup")
async def startup() -> None:
    init_db()
```

### Right

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
```

### Svelte And SvelteKit

#### Project-Level Standard

- New Svelte 5 code should prefer runes APIs such as `$props`, `$state`, `$derived`, and `$effect`.
- Treat top-level legacy `$:` reactivity and other legacy APIs as migration-era compatibility tools, not the default style for new components.
- Do not scatter route fetching logic in components when `+page.ts` or `+layout.ts` should own it.

### Bad

```svelte
<script>
	export let question;
	$: title = question.title.toUpperCase();
</script>
```

### Right

```svelte
<script lang="ts">
	let { question } = $props<{ question: QuestionResponse }>();
	let title = $derived(question.title.toUpperCase());
</script>
```

### Libraries And Framework Choices In This Repo

- No new Flask surface area. FastAPI is the standard for new HTTP work.
- No new Axios or ad hoc fetch wrappers in the web app. `ky` is the standard HTTP client.
- No new `requests` in application code for outbound HTTP. Prefer `httpx` for new Python integrations because it supports modern timeout and async/sync usage patterns.
- No markdown rendering without sanitization.
- No direct browser persistence of auth tokens unless a security review explicitly approves it.

## Dependency Hygiene, Deprecations, And CVE Policy

Dependency management is part of engineering, not housekeeping.

### Upgrade Policy

#### Do

- Keep direct dependencies reasonably current.
- Review major upgrades intentionally, not accidentally.
- Prefer fewer dependencies with clear ownership.
- Use exact lockfiles in CI and deployments.
- Use `pnpm overrides` or Python constraints only as temporary risk controls with an expiry note.

#### Do Not

- Leave internet-facing dependencies stale for months because "nothing broke yet".
- Add duplicate libraries that solve the same problem.
- Ignore transitive vulnerability reports just because they are transitive.

### Security Audit Policy

- Run `pnpm audit` for the web app regularly and in CI.
- Run `pip-audit` for Python dependencies regularly and in CI.
- Review `pnpm outdated` and Python package freshness on a schedule.
- Track security advisories for auth, HTTP, parsing, markdown, templating, and serialization libraries more aggressively than low-risk dev tooling.

### Severity Policy

- Critical direct dependency advisory: block merge and block deployment until fixed or formally risk-accepted by an owner.
- High direct dependency advisory: block merge unless there is a documented mitigation and an immediate upgrade plan.
- Moderate advisory in internet-facing, auth, markdown, parser, templating, or serialization code: fix quickly and do not ignore by default.
- Low advisory in auth, cookie, parser, or HTML-rendering code still deserves review because exploitability can exceed the numeric severity.
- Build-only low advisories can be batched, but never silently.

### Reachability Policy

- Do not stop at CVSS severity.
- Ask whether the vulnerable code path is reachable in this app.
- Ask whether the package sits on an auth, cookie, HTML, or parser boundary.
- Ask whether a safe override, pin, or mitigation exists while waiting for upstream.

### Current Advisory Snapshot

As of 2026-04-03, local `pnpm audit` reported this known advisory in the web dependency graph:

- `cookie` `<0.7.0`, transitive via `@sveltejs/kit`, GitHub advisory `GHSA-pxg6-pf52-xh8x`, `CVE-2024-47764`, low severity.
- Impact summary: cookie `name`, `path`, and `domain` validation allowed out-of-bounds characters.
- Patched version: `cookie` `0.7.0` and later.
- Current repo rule: do not pass untrusted values into cookie names, paths, or domains, and treat transitive auth/cookie parser advisories as fast-follow upgrades, not background noise.

### Bad

```text
It is only a low-severity transitive advisory, so we can ignore it indefinitely.
```

### Right

```text
The advisory is in an auth-adjacent cookie package. Patch it, override it, or document a short-lived mitigation and owner.
```

## Testing Conventions

### General

#### Do

- Test behavior, not implementation trivia.
- Put most tests around pure logic and services.
- Add integration tests for persistence and HTTP boundaries.
- Add regression tests for every non-trivial bug fix.

#### Do Not

- Over-index on snapshots.
- Mock everything until the test proves nothing.
- Write tests that only restate the code.

### Python Tests

#### Do

- Use `pytest`.
- Use fixtures for setup, factories for readable data, and parametrization for matrix-like behavior.
- Test happy paths, failure paths, and edge conditions.
- Keep LLM/provider calls mocked at the service boundary.

#### Do Not

- Make tests depend on real network calls.
- Share mutable global test state.
- Assert against giant opaque strings when structured assertions are available.

### Frontend Tests

#### Do

- Use `svelte-check` and TypeScript as a baseline.
- When adding frontend test coverage, prefer Vitest for unit and component tests and Playwright for end-to-end flows because they fit Vite and SvelteKit well.
- Test user-visible behavior and accessibility-relevant interactions.

#### Do Not

- Treat the DOM as a snapshot artifact only.
- Assert on implementation details like private variable names or exact utility class ordering.

## Performance Conventions

### Do

- Measure before optimizing.
- Cache intentionally, not accidentally.
- Batch database work where it materially reduces round-trips.
- Keep payloads small and explicit.

### Do Not

- Add memoization or caching layers without invalidation rules.
- Load large datasets when summary data is enough.
- Perform expensive work on every request if it can be precomputed safely.

## Reliability Conventions

### Do

- Make retries explicit and bounded.
- Use timeouts for network calls.
- Make background behavior observable.
- Design idempotent operations where retries are likely.

### Do Not

- Retry forever.
- Retry writes that are not safe to replay.
- Depend on default timeouts.

## LLM Integration Conventions

This repo generates and grades content with model providers. That increases the bar.

### Do

- Keep prompts versioned and reviewable.
- Validate model output before saving or returning it.
- Bound retries and fallbacks.
- Keep provider-specific code behind an interface.
- Record enough metadata to debug output quality without leaking secrets.

### Do Not

- Trust model output as already valid JSON or already policy-compliant.
- Scatter prompt strings through routers, UI code, and handlers.
- Couple core logic to one provider SDK.

### Bad

```python
response = client.messages.create(...)
question = json.loads(response.content[0].text)
save_question(question)
```

### Right

```python
raw = provider.generate(prompt)
draft = QuestionDraft.model_validate_json(raw)
repository.save_draft(draft)
```

## Example Playbook

This section shows how the conventions above should look in real code and real repo structure.

### Example 1: Feature Layout Once A Feature Stops Being Trivial

Default for non-trivial backend features:

```text
src/swet_api/
  routers/
    attempts.py
  services/
    attempt_service.py
  repositories/
    attempt_repository.py
  schemas/
    attempts.py
  engine/
    grading.py
tests/
  test_api/
    test_attempts.py
  test_services/
    test_attempt_service.py
  test_repositories/
    test_attempt_repository.py
```

Accepted exception for very small features:

```text
src/swet_api/
  routers/
    health.py
tests/
  test_api/
    test_health.py
```

Avoid this:

```text
src/
  helpers.py
  utils.py
  handlers.py
  db_stuff.py
  logic.py
```

### Example 2: Router, Service, Repository Split

Bad once the endpoint has real logic:

```python
@router.post("/attempts")
def submit_attempt(req: dict):
    row = conn.execute(
        "SELECT * FROM questions WHERE id = ?",
        (req["question_id"],),
    ).fetchone()
    score = grade_answer(req["answer_text"], row["grading_rubric"])
    conn.execute(
        "INSERT INTO attempts (question_id, answer_text, score) VALUES (?, ?, ?)",
        (req["question_id"], req["answer_text"], score.total_score),
    )
    conn.commit()
    return {"score": score.total_score}
```

Default for trivial endpoints:

```python
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

Scale-up path when a feature has orchestration, multiple queries, or reusable rules:

```python
@router.post("/attempts", response_model=GradeResponse)
def submit_attempt(req: AnswerRequest, user: CurrentUser, service: AttemptServiceDep) -> GradeResponse:
    return service.submit_attempt(user_id=user.id, request=req)
```

```python
class AttemptService:
    def __init__(self, questions: QuestionRepository, attempts: AttemptRepository) -> None:
        self.questions = questions
        self.attempts = attempts

    def submit_attempt(self, user_id: str, request: AnswerRequest) -> GradeResponse:
        question = self.questions.get_for_user(user_id=user_id, question_id=request.question_id)
        if question is None:
            raise QuestionNotFoundError(request.question_id)

        result = grade_attempt(
            answer_text=request.answer_text,
            rubric=question.grading_rubric,
        )

        return self.attempts.save_result(
            user_id=user_id,
            question=question,
            answer_text=request.answer_text,
            result=result,
        )
```

```python
class AttemptRepository:
    def save_result(
        self,
        user_id: str,
        question: QuestionRecord,
        answer_text: str,
        result: GradeResult,
    ) -> GradeResponse:
        with self.transaction() as conn:
            attempt_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO attempts (id, user_id, question_id, answer_text, score, max_score)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    user_id,
                    question.id,
                    answer_text,
                    result.total_score,
                    result.max_score,
                ),
            )
        return GradeResponse(
            attempt_id=attempt_id,
            score=result.total_score,
            max_score=result.max_score,
            total_score=result.total_score,
            normalized_score=result.normalized_score,
            criteria_scores=result.criteria_scores,
            overall_feedback=result.overall_feedback,
            explanation=result.explanation,
            correct_answer=result.correct_answer,
        )
```

### Example 3: Secure SPA Auth

Bad as an unreviewed default:

```ts
const tokens = await api.post('auth/login', { json: credentials }).json<TokenResponse>();
localStorage.setItem('access_token', tokens.access_token);
localStorage.setItem('refresh_token', tokens.refresh_token);
```

Preferred default when same-origin deployment is stable:

```python
@router.post("/auth/login", response_model=SessionResponse)
def login(req: LoginRequest, response: Response, service: AuthServiceDep) -> SessionResponse:
    session = service.login(req)
    response.set_cookie(
        key="refresh_token",
        value=session.refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/auth",
    )
    return SessionResponse(
        access_token=session.access_token,
        csrf_token=session.csrf_token,
        user=session.user,
    )
```

```ts
const session = await api.post('auth/login', { json: credentials }).json<SessionResponse>();
auth.setSession(session.access_token, session.user, session.csrf_token);
```

```ts
export async function savePreferences(
	payload: PreferencesRequest,
	csrfToken: string,
): Promise<PreferencesResponse> {
	return api.put('preferences', {
		json: payload,
		headers: { 'X-CSRF-Token': csrfToken }
	}).json<PreferencesResponse>();
}
```

Accepted exception for a small static SPA with explicit risk acceptance:

```ts
const tokens = await api.post('auth/login', { json: credentials }).json<TokenResponse>();
auth.setAccessToken(tokens.access_token);
localStorage.setItem('refresh_token', tokens.refresh_token);
```

```text
Only acceptable if the deployment is intentionally same-origin-light, CSP is strict, HTML is sanitized, token TTLs are short, and the tradeoff is documented.
```

### Example 4: Slow Provider Call Default Vs Scale-Up Path

Bad once latency is already a problem:

```python
@router.post("/questions/generate", response_model=list[QuestionResponse])
def generate(req: GenerateRequest, user: CurrentUser) -> list[QuestionResponse]:
    raw = llm_provider.generate(prompt_builder.build(req), timeout=120)
    return question_repository.save_batch(user.id, parse_questions(raw))
```

Default for low-traffic interactive flows:

```python
@router.post("/questions/generate", response_model=list[QuestionResponse])
def generate(req: GenerateRequest, user: CurrentUser) -> list[QuestionResponse]:
    prompt = prompt_builder.build(req)
    raw = llm_provider.generate(prompt, timeout=20)
    questions = parse_questions(raw)
    return question_repository.save_batch(user.id, questions)
```

Scale-up path when p95 latency, retries, or provider reliability stop fitting the request path:

```python
@router.post("/question-jobs", response_model=GenerationJobAccepted, status_code=202)
def create_question_job(
    req: GenerateRequest,
    user: CurrentUser,
    service: GenerationJobServiceDep,
) -> GenerationJobAccepted:
    return service.enqueue(user_id=user.id, request=req)
```

```python
class GenerationJobWorker:
    def run(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        draft = self.generator.generate(job.request)
        questions = [QuestionDraft.model_validate(item) for item in draft]
        self.questions.save_batch(job.user_id, questions)
        self.jobs.mark_completed(job_id)
```

```ts
const job = await api.post('question-jobs', { json: payload }).json<GenerationJobAccepted>();
const result = await pollJobUntilComplete(job.job_id);
```

### Example 5: Bounded Reads First, Cursor Pagination Later

Bad:

```python
def list_attempts_for_user(user_id: str) -> list[AttemptRecord]:
    rows = conn.execute(
        "SELECT * FROM attempts WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [AttemptRecord.model_validate(dict(row)) for row in rows]
```

Default:

```python
def list_recent_attempts_for_user(user_id: str, limit: int = 50) -> list[AttemptRecord]:
    rows = conn.execute(
        """
        SELECT id, question_id, title, created_at, score
        FROM attempts
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [AttemptRecord.model_validate(dict(row)) for row in rows]
```

Scale-up path:

```python
def list_attempts_for_user(
    user_id: str,
    cursor: str | None,
    limit: int,
) -> AttemptHistoryPage:
    bound = cursor or "9999-12-31T23:59:59+00:00"
    rows = conn.execute(
        """
        SELECT id, question_id, title, created_at, score
        FROM attempts
        WHERE user_id = ? AND created_at < ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, bound, limit + 1),
    ).fetchall()

    items = [AttemptHistoryItem.model_validate(dict(row)) for row in rows[:limit]]
    next_cursor = items[-1].created_at if len(rows) > limit else None
    return AttemptHistoryPage(items=items, next_cursor=next_cursor)
```

### Example 6: Frontend Route Data, Not Component Fetch Sprawl

Bad:

```svelte
<script lang="ts">
	let questions = $state<QuestionResponse[]>([]);
	let loading = $state(true);

	(async () => {
		questions = await api.get('questions').json<QuestionResponse[]>();
		loading = false;
	})();
</script>
```

Right:

```ts
// src/routes/(app)/train/+page.ts
import { getNextQuestion } from '$lib/api/questions';

export async function load() {
	return {
		question: await getNextQuestion()
	};
}
```

```svelte
<!-- src/routes/(app)/train/+page.svelte -->
<script lang="ts">
	import type { PageData } from './$types';
	import { submitAnswer } from '$lib/api/attempts';

	let { data }: { data: PageData } = $props();
	let answer = $state('');
	let submitting = $state(false);

	async function submit() {
		submitting = true;
		try {
			await submitAnswer({
				question_id: data.question.id,
				answer_text: answer
			});
		} finally {
			submitting = false;
		}
	}
</script>
```

```ts
// src/lib/api/questions.ts
export async function getNextQuestion(): Promise<QuestionResponse | null> {
	return api.get('questions/next').json<QuestionResponse | null>();
}
```

### Example 7: Contract Sync Between FastAPI And TypeScript

Bad:

```python
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
```

```ts
export interface TokenResponse {
	accessToken: string;
	refreshToken: string;
}
```

Right:

```python
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
```

```ts
import type { components } from '$lib/api/generated';

export type TokenResponse = components['schemas']['TokenResponse'];
```

### Example 8: Markdown Rendering With A Single Safe Boundary

Bad:

```svelte
<script lang="ts">
	import { marked } from 'marked';
	let html = marked.parse(content) as string;
</script>

<article>{@html html}</article>
```

Right:

```ts
// src/lib/utils/markdown.ts
import { marked } from 'marked';
import DOMPurify from 'dompurify';

export function renderMarkdown(text: string): string {
	const raw = marked.parse(text, { async: false }) as string;
	return DOMPurify.sanitize(raw);
}
```

```svelte
<script lang="ts">
	import { renderMarkdown } from '$lib/utils/markdown';
	let { content }: { content: string } = $props();
	let html = $derived(renderMarkdown(content));
</script>

<article>{@html html}</article>
```

### Example 9: Test The Service And The Boundary Separately

Bad:

```python
def test_submit_attempt_calls_everything(mocker):
    ...
    assert repository.save.called
    assert grader.grade.called
    assert logger.info.called
```

Right:

```python
def test_submit_attempt_returns_grade_response(question_repository, attempt_repository):
    service = AttemptService(question_repository, attempt_repository)

    result = service.submit_attempt(
        user_id="u1",
        request=AnswerRequest(question_id="q1", answer_text="O(log n)"),
    )

    assert result.score == 5
    assert result.max_score == 5
```

```python
def test_post_attempts_returns_404_for_unknown_question(client, auth_headers):
    response = client.post(
        "/attempts",
        headers=auth_headers,
        json={"question_id": "missing", "answer_text": "test"},
    )

    assert response.status_code == 404
```

### Example 10: Responding To A CVE

Bad:

```text
Dependabot says a transitive auth-related package is vulnerable. We will wait until a random future cleanup sprint.
```

Right:

```json
{
	"pnpm": {
		"overrides": {
			"cookie": "0.7.0"
		}
	}
}
```

```text
Temporary mitigation only. Verify compatibility, track an owner, and remove the override once the upstream package releases a patched dependency range.
```

### Example 11: Configuration At The Edge

Bad:

```python
def send_otp(destination: str, code: str) -> None:
    provider = os.getenv("OTP_PROVIDER", "console")
    api_key = os.getenv("TWILIO_AUTH_TOKEN")
    ...
```

Right:

```python
class MessagingConfig(BaseModel):
    provider: Literal["console", "twilio"]
    twilio_auth_token: SecretStr | None = None


def get_messaging_config() -> MessagingConfig:
    return MessagingConfig(
        provider=os.environ.get("OTP_PROVIDER", "console"),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN"),
    )


class OtpService:
    def __init__(self, config: MessagingConfig, provider: OtpProvider) -> None:
        self.config = config
        self.provider = provider
```

### Example 12: Single Source Of State Ownership

Bad:

```ts
export const auth = createAuthStore();
export const user = createUserStore();
export const session = createSessionStore();
export const nav = createNavStore();
```

Right:

```ts
interface AuthSession {
	user: UserResponse | null;
	accessToken: string | null;
	csrfToken: string | null;
}

function createAuthStore() {
	let session = $state<AuthSession>({
		user: null,
		accessToken: null,
		csrfToken: null
	});

	return {
		get user() {
			return session.user;
		},
		get accessToken() {
			return session.accessToken;
		},
		get csrfToken() {
			return session.csrfToken;
		},
		setSession(accessToken: string, user: UserResponse, csrfToken: string) {
			session = { accessToken, user, csrfToken };
		},
		clear() {
			session = { accessToken: null, user: null, csrfToken: null };
		}
	};
}
```

## Formatting And Tooling

### Python

- Ruff is the formatter and linter.
- mypy strict mode is required.
- Keep import order canonical.
- Do not fight the formatter.

### Web

- Use `pnpm`, not `npm` or `yarn`, in `web/`.
- Keep TypeScript strict.
- Run formatting and linting before merge.
- `pnpm build` must stay green.
- Security audits are part of the toolchain, not optional cleanup.

### Required Checks Before Merge

- `python -m pytest`
- `python -m ruff check src tests`
- `python -m ruff format --check src tests`
- `python -m mypy src`
- `cd web && pnpm check`
- `cd web && pnpm lint`
- `cd web && pnpm build`

Recommended security checks on protected branches:

- `cd web && pnpm audit`
- `.venv/bin/python -m pip-audit`

If a change only touches backend code, the frontend checks may be skipped deliberately, but that decision should be explicit. The same applies in reverse.

## Git And Review Conventions

### Do

- Keep pull requests focused.
- Explain intent, risk, and migration impact.
- Include tests with behavior changes.
- Prefer follow-up PRs over giant mixed refactors.

### Do Not

- Mix formatting, refactoring, bug fixes, and feature work without reason.
- Sneak schema changes into unrelated PRs.
- Merge behavior changes that are not covered by tests or documented manual verification.

## Documentation Conventions

### Do

- Document decisions that are non-obvious, risky, or irreversible.
- Keep README-level docs accurate.
- Record auth, env, and deployment requirements near the code that uses them.

### Do Not

- Leave stale setup instructions in the repo.
- Use comments to excuse bad code that should be simplified instead.

## Explicit Prohibitions

- No new `print()` debugging in application code.
- No new `Any` in production code without an inline justification.
- No new browser storage of refresh tokens.
- No wildcard production CORS for authenticated endpoints.
- No direct SQL in routers, handlers, or UI-triggered code.
- No direct `fetch` or `ky` calls inside random Svelte components when an API module should own the call.
- No hand-maintained duplicate API contracts when generated types are practical.
- No broad `except Exception:` without narrowing, logging, and a clear recovery path.
- No framework magic when plain typed code is clearer.
- No new Flask services for HTTP work.
- No new Pydantic V1 compatibility APIs in new code.
- No new FastAPI startup or shutdown event handlers when `lifespan` should be used.
- No raw `{@html}` from unsanitized content.
- No silent acceptance of known high or critical CVEs.
- No direct long-running provider calls in hot request paths once they exceed the latency budget.

## Decision Heuristics

When in doubt:

- Prefer the simpler design.
- Prefer the more typed design.
- Prefer the design with fewer hidden side effects.
- Prefer the design with fewer cross-layer dependencies.
- Prefer the design that is easier to test.
- Prefer the design that keeps secrets and auth state out of the browser.

If a proposed change violates one of these conventions, it should include a short written justification and an expiry plan.
