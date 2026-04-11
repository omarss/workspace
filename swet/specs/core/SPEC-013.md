# SPEC-013: Question Caching Layer

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-012 (Question generation via Claude)

## Overview
The question caching layer ensures that Claude API calls are made only when necessary. Question pools are indexed by `config_hash` (derived from the user's role and technology selections), `competency_id`, `difficulty`, and `format`. When a user starts an assessment, the system looks up existing pools matching their `config_hash`. If pools are missing, generation is triggered. If generation is already in progress for a given pool, duplicate generation is prevented using PostgreSQL advisory locks.

This layer sits between the assessment engine (SPEC-014) and the question generator (SPEC-012), providing a pool management interface that handles lifecycle tracking, concurrent access, and cache invalidation.

## Requirements

### Functional
1. Question pools are uniquely identified by the combination of `(config_hash, competency_id, difficulty, format)`.
2. Pool lookup: given a `config_hash`, the system can determine which pools exist and their current status.
3. Pool statuses follow this lifecycle: `pending` -> `generating` -> `complete` | `failed`.
4. When a required pool does not exist, a new pool record is created with status `pending` and generation is triggered asynchronously.
5. PostgreSQL advisory locks (keyed on a hash of `config_hash + competency_id + difficulty + format`) prevent two concurrent requests from triggering duplicate generation for the same pool.
6. If a pool is in `generating` status, the caller waits (with polling) rather than triggering a new generation.
7. Failed pools can be retried: setting status back to `pending` and re-triggering generation.
8. Pool status includes `total_questions` count, updated after successful generation.
9. The system can determine pool readiness for a given `config_hash`: all required pools (across all competencies, difficulties, and formats) must be `complete` before an assessment can be assembled.

### Non-Functional
1. Advisory lock acquisition must complete within 5 seconds or fail gracefully.
2. Pool status polling interval should be 2 seconds, with a maximum wait of 120 seconds before timing out.
3. A user's assessment creation should not be blocked for more than 2 minutes waiting for generation.
4. Pool lookups should be indexed for sub-millisecond query time.

## Technical Design

### Pool Lookup Pattern
```
get_or_create_pool(config_hash, competency_id, difficulty, format)
  -> SELECT from question_pools WHERE config_hash, competency_id, difficulty, format
  -> if exists and status == "complete": return pool
  -> if exists and status == "generating": poll until complete or timeout
  -> if exists and status == "failed": reset to pending, trigger generation
  -> if not exists: INSERT with status "pending", trigger generation
```

### Advisory Lock Strategy
PostgreSQL advisory locks are session-level locks that do not conflict with row-level locks. They are used here to coordinate concurrent pool generation.

```python
async def acquire_generation_lock(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    difficulty: int,
    format: str,
) -> bool:
    """Acquire an advisory lock for pool generation.

    Returns True if lock acquired, False if another session holds it.
    Uses pg_try_advisory_lock to avoid blocking.
    """
    # Compute a stable 64-bit integer from the pool key
    lock_key = compute_lock_key(config_hash, competency_id, difficulty, format)
    result = await db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": lock_key},
    )
    return result.scalar()
```

```python
def compute_lock_key(
    config_hash: str,
    competency_id: int,
    difficulty: int,
    format: str,
) -> int:
    """Compute a 64-bit lock key from pool identifiers."""
    key_str = f"{config_hash}:{competency_id}:{difficulty}:{format}"
    # Use first 8 bytes of SHA-256, interpreted as signed 64-bit int
    hash_bytes = hashlib.sha256(key_str.encode()).digest()[:8]
    return int.from_bytes(hash_bytes, byteorder="big", signed=True)
```

### Pool Status Transitions
```
                  +-----------+
                  |  pending  |
                  +-----+-----+
                        |
                  acquire lock
                        |
                  +-----v-----+
            +---->| generating|
            |     +-----+-----+
            |           |
            |     +-----+-----+
            |     |           |
            | +---v---+  +----v----+
            | |complete|  | failed  |
            | +-------+  +----+----+
            |                  |
            +------ retry -----+
```

### Database Table
Uses existing `question_pools` table:
- `id` (UUID, PK)
- `config_hash` (VARCHAR(64), indexed)
- `competency_id` (SMALLINT, FK -> competencies.id)
- `difficulty` (SMALLINT, 1-5)
- `format` (VARCHAR(30))
- `total_questions` (INTEGER, default 0)
- `generation_status` (VARCHAR(20), default "pending")
- `created_at`, `updated_at` (TIMESTAMPTZ)

Index: composite index on `(config_hash, competency_id, difficulty, format)` for fast lookups.

### Cache Invalidation Strategy
1. **Profile update**: When a user updates their profile and their `config_hash` changes, no pools are deleted. The new `config_hash` simply points to different (or not-yet-created) pools. Old pools remain available for other users with the same config.
2. **Stale pools**: Pools older than 90 days can be garbage-collected via a periodic cleanup task (not in scope for this spec, but the `created_at` field supports it).
3. **Failed pools**: Automatically retried on next access. If a pool has been in `failed` status for more than 1 hour, it is eligible for retry.
4. **Manual invalidation**: An admin CLI command can delete all pools for a given `config_hash` to force regeneration.

### Service Module (`src/questions/cache.py`)
```python
async def ensure_pools_ready(
    db: AsyncSession,
    config_hash: str,
    role: str,
    role_context: dict,
) -> bool:
    """Ensure all required pools exist and are complete.

    Triggers generation for any missing or failed pools.
    Returns True if all pools are ready, False if still generating.
    """

async def get_pool(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    difficulty: int,
    format: str,
) -> QuestionPool | None:
    """Lookup a specific pool."""

async def get_or_create_pool(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    difficulty: int,
    format: str,
    role_context: dict,
) -> QuestionPool:
    """Get an existing pool or create and trigger generation."""
```

## Implementation Notes
- Advisory locks are preferred over row-level `SELECT FOR UPDATE` because they do not require an existing row and do not interfere with regular read queries.
- The lock key computation uses a 64-bit signed integer because PostgreSQL advisory locks accept `bigint` parameters.
- Pool generation is triggered as a background task (FastAPI `BackgroundTasks`) so the API response is not blocked. The frontend polls for readiness.
- The number of required pools per assessment depends on the role weights (SPEC-011), format distribution (SPEC-012), and difficulty distribution (SPEC-014). Not every combination needs a pool: only those that will actually have questions selected.
- A `config_hash` index on the `question_pools` table is essential for fast lookups. The existing indexed column supports this.

## Testing Strategy
- **Unit tests**: `compute_lock_key` produces consistent 64-bit integers, pool status transitions are valid, cache lookup logic returns correct results for each status.
- **Integration tests**: Create pool -> set to generating -> set to complete lifecycle. Advisory lock prevents duplicate generation (simulate two concurrent requests). Failed pool retry resets status and re-triggers generation. Pool lookup by `(config_hash, competency_id, difficulty, format)` returns correct results.
- **Concurrency tests**: Two async tasks attempting to generate the same pool simultaneously: only one acquires the lock, the other waits/polls.

## Acceptance Criteria
- [ ] Pools are uniquely identified by `(config_hash, competency_id, difficulty, format)`.
- [ ] Missing pools are created with `pending` status and trigger generation.
- [ ] Advisory locks prevent duplicate generation for the same pool.
- [ ] Pool status transitions follow the defined lifecycle: pending -> generating -> complete/failed.
- [ ] Completed pools are reused across users with the same `config_hash`.
- [ ] Failed pools are retried on next access after the retry cooldown period.
- [ ] `ensure_pools_ready` correctly reports whether all required pools are complete.
- [ ] Pool lookup queries use the composite index and complete in sub-millisecond time.
- [ ] Generation is triggered as a background task (non-blocking API response).
- [ ] Poll timeout (120s) is enforced and returns an appropriate error if exceeded.
