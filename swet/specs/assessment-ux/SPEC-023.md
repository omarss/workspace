# SPEC-023: Question Uniqueness Enforcement

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-013
- SPEC-014

## Overview
Ensures that a user never sees the same question twice across assessments. A `user_question_history` table records every question served to a user. During assessment creation, the question selection query excludes previously seen questions. When the available question pool is exhausted for a given competency and difficulty combination, the system triggers on-demand generation of new questions (delegating to SPEC-012).

## Requirements

### Functional
1. A `user_question_history` table records each (user, question) pair with a timestamp of when it was first served.
2. A `UNIQUE(user_id, question_id)` constraint on `user_question_history` prevents duplicate entries at the database level.
3. When an assessment is created, all selected question IDs are batch-inserted into `user_question_history` in a single transaction alongside the assessment creation.
4. The question selection query (from SPEC-014) must include a `NOT IN (SELECT question_id FROM user_question_history WHERE user_id = $1)` filter (or equivalent `LEFT JOIN ... IS NULL` anti-join) to exclude seen questions.
5. If the available unseen question pool for a required (competency, difficulty) combination has fewer questions than needed, the system triggers new question generation via the generation pipeline (SPEC-012) to fill the gap.
6. A minimum pool buffer threshold is configurable (default: 20 questions per competency-difficulty pair). When the unseen pool drops below this threshold, background generation is triggered proactively, even if the current assessment can still be filled.
7. The history lookup must be efficient for users who have taken many assessments (potentially thousands of seen questions over time).

### Non-Functional
1. The `user_question_history` insert batch must complete within 100ms for 100 questions.
2. The question selection query with exclusion must complete within 200ms even when the history table contains 10,000+ rows for a single user.
3. The uniqueness constraint must be enforced at the database level, not only in application code, to prevent race conditions from concurrent assessment creation.
4. Triggering new question generation must not block assessment creation. If the pool is insufficient and generation is needed, the assessment creation should still proceed with whatever unique questions are available and backfill the remainder asynchronously, or fail gracefully with a clear error if zero questions are available.

## Technical Design

### Database Changes

```sql
CREATE TABLE user_question_history (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_id   UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT uq_user_question UNIQUE (user_id, question_id)
);

CREATE INDEX idx_uqh_user_id ON user_question_history (user_id);
CREATE INDEX idx_uqh_user_question ON user_question_history (user_id, question_id);
```

- `assessment_id` is stored for auditability (which assessment introduced this question to the user) but is not part of the unique constraint.
- `ON DELETE CASCADE` on `user_id` ensures cleanup when a user account is deleted.
- `ON DELETE CASCADE` on `question_id` ensures stale entries are removed if a question is retired.

### Question Selection Query (augmented from SPEC-014)

```sql
SELECT q.id
FROM questions q
LEFT JOIN user_question_history uqh
  ON uqh.question_id = q.id AND uqh.user_id = $1
WHERE q.competency = $2
  AND q.difficulty = $3
  AND q.status = 'active'
  AND uqh.id IS NULL
ORDER BY RANDOM()
LIMIT $4;
```

The `LEFT JOIN ... IS NULL` pattern is preferred over `NOT IN` for performance with large history tables.

### History Recording

During assessment creation (transaction):

```sql
BEGIN;

INSERT INTO assessments (...) VALUES (...) RETURNING id;

INSERT INTO user_question_history (user_id, question_id, assessment_id, seen_at)
SELECT $user_id, unnest($question_ids::uuid[]), $assessment_id, now()
ON CONFLICT (user_id, question_id) DO NOTHING;

INSERT INTO assessment_questions (...) VALUES (...);

COMMIT;
```

`ON CONFLICT DO NOTHING` handles the unlikely edge case where a race condition causes a duplicate (e.g., two concurrent assessment creations select the same question before either commits). The second assessment simply skips re-recording it.

### Pool Exhaustion Handling

```
src/lib/question-pool.ts
```

```tsx
async function selectUniqueQuestions(
  userId: string,
  competency: string,
  difficulty: string,
  count: number
): Promise<{ questions: Question[]; deficit: number }> {
  const available = await queryAvailableQuestions(userId, competency, difficulty, count);

  const deficit = count - available.length;

  if (deficit > 0) {
    // Trigger async generation for the deficit + buffer
    await enqueueQuestionGeneration({
      competency,
      difficulty,
      count: deficit + POOL_BUFFER_THRESHOLD,
    });
  }

  return { questions: available, deficit };
}
```

- If `deficit > 0` and the caller requires all questions, the assessment creation can either: (a) proceed with a partial set and fill in later, or (b) return an error indicating insufficient questions. The default behavior is (b) -- return an error -- since a partial assessment would confuse the user.
- The `enqueueQuestionGeneration` call is fire-and-forget (non-blocking), ensuring the pool is replenished for the next attempt.

### Proactive Buffer Check

A utility function runs after each assessment creation to check remaining pool sizes:

```tsx
async function checkPoolBuffers(userId: string, competencies: string[]): Promise<void> {
  for (const competency of competencies) {
    for (const difficulty of ['junior', 'mid', 'senior']) {
      const remaining = await countAvailableQuestions(userId, competency, difficulty);
      if (remaining < POOL_BUFFER_THRESHOLD) {
        await enqueueQuestionGeneration({
          competency,
          difficulty,
          count: POOL_BUFFER_THRESHOLD - remaining,
        });
      }
    }
  }
}
```

This runs asynchronously after the assessment is successfully created, so it does not impact response time.

## Implementation Notes
- The `LEFT JOIN ... IS NULL` anti-join pattern typically outperforms `NOT IN` or `NOT EXISTS` on PostgreSQL for large exclusion sets because it allows the planner to use a hash anti-join.
- The composite index on `(user_id, question_id)` serves double duty: it backs the unique constraint and accelerates the anti-join lookup.
- The `POOL_BUFFER_THRESHOLD` (default 20) should be configurable via environment variable (`QUESTION_POOL_BUFFER=20`) to allow tuning without code changes.
- When a user has exhausted nearly all questions in a competency, the proactive generation becomes critical. The generation pipeline (SPEC-012) must be able to produce questions that are semantically distinct from existing ones. This is outside the scope of this spec but is a dependency worth noting.
- Consider adding a `user_question_history` summary view or materialized count per user for admin dashboards, but this is out of scope for this spec.

## Testing Strategy
- **Unit tests (Vitest):** Test `selectUniqueQuestions` logic: mock database queries to return varying pool sizes, verify correct deficit calculation and generation trigger.
- **Unit tests (Vitest):** Test `checkPoolBuffers`: verify generation is enqueued only when remaining count is below threshold.
- **Integration tests (Vitest + test database):** Insert a user with known history, run the selection query, verify excluded questions do not appear in results.
- **Integration tests (Vitest + test database):** Attempt to insert a duplicate `(user_id, question_id)` pair, verify `ON CONFLICT DO NOTHING` prevents error and does not duplicate.
- **Integration tests (Vitest + test database):** Create an assessment via the full transaction, verify both `assessments` and `user_question_history` rows are created atomically (commit) or neither is created (rollback on failure).
- **Load test:** Insert 10,000 history rows for a single user, run the selection query, verify it completes within 200ms.

## Acceptance Criteria
- [ ] `user_question_history` table is created with `UNIQUE(user_id, question_id)` constraint
- [ ] Assessment creation batch-inserts all selected question IDs into the history table within the same transaction
- [ ] Question selection query excludes all previously seen questions for the user
- [ ] Duplicate `(user_id, question_id)` inserts are handled gracefully via `ON CONFLICT DO NOTHING`
- [ ] When unseen pool is insufficient, question generation is triggered asynchronously
- [ ] Proactive buffer check runs after assessment creation and triggers generation when pool is below threshold
- [ ] Selection query with exclusion completes within 200ms with 10,000+ history rows
- [ ] History batch insert for 100 questions completes within 100ms
- [ ] `POOL_BUFFER_THRESHOLD` is configurable via environment variable
- [ ] User account deletion cascades to remove their question history
