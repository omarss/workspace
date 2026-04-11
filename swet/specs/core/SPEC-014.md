# SPEC-014: Assessment Engine

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-010 (User onboarding flow)
- SPEC-011 (Competency and role definitions)
- SPEC-013 (Question caching layer)

## Overview
The assessment engine is the core orchestrator of SWET. It assembles a 100-question assessment tailored to the user's role by selecting questions from cached pools according to role-specific competency weights, distributing difficulty levels along a bell curve, respecting format distribution targets, and excluding previously seen questions. The engine also manages the full assessment lifecycle (create -> in_progress -> completed) and handles answer submission with auto-save support.

## Requirements

### Functional
1. Each assessment contains exactly 100 questions.
2. Questions are selected per competency according to `role_competency_weights.question_count` for the user's role (e.g., a backend developer gets 12 problem_solving questions, 10 code_quality questions, etc.).
3. Within each competency's allocation, difficulty is distributed following a bell curve:
   - L1 (beginner): 10%
   - L2 (intermediate): 20%
   - L3 (advanced): 35%
   - L4 (expert): 25%
   - L5 (principal): 10%
4. Question format distribution targets (applied globally across the assessment):
   - MCQ: 40%
   - Code Review: 15%
   - Debugging: 15%
   - Short Answer: 15%
   - Design Prompt: 15%
5. Questions the user has previously seen (tracked in `user_question_history`) are excluded from selection.
6. Within each `(competency, difficulty, format)` bucket, questions are selected randomly.
7. The final 100 questions are interleaved (shuffled) so that competencies, difficulties, and formats are mixed throughout the assessment rather than grouped.
8. Assessment lifecycle states: `in_progress` (on creation) -> `completed` (on submission or timeout).
9. Answers support upsert semantics: auto-save updates the answer without marking it as submitted; explicit submit sets `submitted_at` and `is_auto_saved = False`.
10. Time spent per question is tracked via `time_spent_seconds` on each answer.
11. Assessment creation requires all relevant question pools to be in `complete` status.

### Non-Functional
1. Assessment assembly (question selection + shuffle) must complete in under 3 seconds.
2. The selection algorithm must be deterministic for a given random seed (for reproducibility in testing).
3. If insufficient questions exist in a bucket (after excluding seen questions), the engine should fall back to nearby difficulty levels within the same competency.
4. The assessment state must be consistent: no partial assembly. If assembly fails, the assessment is rolled back.

## Technical Design

### Question Selection Algorithm

```
select_questions(user_id, config_hash, role) -> list[AssessmentQuestion]:
    1. Load role_competency_weights for the role (12 entries, sum = 100)
    2. For each competency:
        a. Compute difficulty distribution:
           - total_for_competency = question_count (from weights)
           - L1 = round(total * 0.10)
           - L2 = round(total * 0.20)
           - L3 = round(total * 0.35)
           - L4 = round(total * 0.25)
           - L5 = round(total * 0.10)
           - Adjust for rounding errors to ensure sum equals total_for_competency
        b. For each difficulty level:
           - Compute format split (40% MCQ, 15% each for others)
           - Query pools by (config_hash, competency_id, difficulty, format)
           - Exclude questions in user_question_history
           - Select randomly from remaining questions
        c. Fallback: if a bucket has insufficient questions, borrow from
           adjacent difficulty levels (prefer L3 as fallback center)
    3. Combine all selected questions (should total 100)
    4. Interleaved shuffle: arrange so consecutive questions differ in
       competency and format where possible
    5. Assign position (0-99) to each question
    6. Insert AssessmentQuestion records
    7. Insert UserQuestionHistory records for all selected questions
```

### Difficulty Distribution Example

For a competency with `question_count = 12`:
| Level | Percentage | Count |
|---|---|---|
| L1 | 10% | 1 |
| L2 | 20% | 2 |
| L3 | 35% | 4 |
| L4 | 25% | 3 |
| L5 | 10% | 2 |
| **Total** | | **12** |

Rounding adjustment: distribute remainders starting from L3 outward.

### Interleaved Shuffle Strategy
The shuffle ensures diversity in the question sequence:
1. Group selected questions by competency.
2. Sort groups by size (largest first).
3. Distribute questions round-robin across positions, pulling from the largest group first.
4. Within each round-robin pass, vary the format to avoid consecutive same-format questions.

This prevents scenarios like 12 consecutive problem_solving questions or 5 MCQs in a row.

### Assessment Lifecycle

```
                  +-------------+
                  | in_progress |
                  +------+------+
                         |
              +----------+----------+
              |                     |
        user submits           time expires
              |                     |
        +-----v-----+        +-----v-----+
        | completed  |        | completed  |
        +-----------+        +-----------+
```

### API Endpoints
- `POST /api/v1/assessments` - Create a new assessment. Triggers question selection. Returns `AssessmentResponse` (201).
- `GET /api/v1/assessments` - List user's assessments. Returns `AssessmentListResponse`.
- `GET /api/v1/assessments/{id}` - Get assessment details. Returns `AssessmentResponse`.
- `GET /api/v1/assessments/{id}/questions` - Get assessment questions (paginated, no correct answers). Returns list of `QuestionResponse`.
- `GET /api/v1/assessments/{id}/questions/{position}` - Get a single question by position. Returns `QuestionResponse`.
- `POST /api/v1/assessments/{id}/answers` - Submit or auto-save an answer. Returns `AnswerResponse`.
- `GET /api/v1/assessments/{id}/progress` - Get progress summary. Returns `ProgressResponse`.
- `POST /api/v1/assessments/{id}/complete` - Mark assessment as completed. Returns `AssessmentResponse`.

### Database Tables
Uses existing tables:

#### `assessments`
- `id`, `user_id`, `config_hash`, `status`, `total_questions`, `current_question_index`
- `is_timed`, `time_limit_minutes`, `started_at`, `completed_at`

#### `assessment_questions`
- `id`, `assessment_id`, `question_id`, `position`, `competency_id`
- Unique constraints: `(assessment_id, position)`, `(assessment_id, question_id)`

#### `answers`
- `id`, `assessment_id`, `question_id`, `user_id`
- `response_text`, `selected_option`, `time_spent_seconds`
- `is_auto_saved`, `submitted_at`
- Unique constraint: `(assessment_id, question_id)`

#### `user_question_history`
- `id`, `user_id`, `question_id`, `seen_at`
- Unique constraint: `(user_id, question_id)`

### Service Module (`src/assessments/service.py`)
Key functions:
```python
async def create_assessment(db, user_id, config_hash, data) -> Assessment
async def select_questions(db, assessment_id, user_id, config_hash, role) -> list[AssessmentQuestion]
async def get_assessment(db, assessment_id, user_id) -> Assessment
async def list_assessments(db, user_id) -> list[Assessment]
async def submit_answer(db, assessment_id, user_id, data) -> Answer
async def complete_assessment(db, assessment_id, user_id) -> Assessment
async def get_progress(db, assessment_id, user_id) -> dict
```

## Implementation Notes
- The selection algorithm must handle the combined constraints of competency counts, difficulty distribution, and format distribution simultaneously. In practice, format distribution is a soft target: the algorithm prioritizes competency and difficulty accuracy, then distributes formats as close to the target as available pools allow.
- The rounding adjustment for difficulty distribution uses a "largest remainder" method: compute exact fractional counts, floor all, then distribute remainders to levels with the largest fractional parts.
- The interleaved shuffle is inspired by the "round-robin with jitter" approach: deterministic enough for testing but appearing random to the user.
- Auto-save creates or updates an answer with `is_auto_saved = True`. Explicit submit sets `is_auto_saved = False` and `submitted_at` to the current timestamp. This distinction matters for the grading engine (SPEC-030/031): only submitted answers are graded.
- `current_question_index` on the assessment model tracks the user's navigation position, updated by the frontend on question transitions.
- Assessment creation is transactional: if question selection fails partway through, the entire assessment (including partial `assessment_questions` rows) is rolled back.

### Recommended Hardening
- Treat `POST /api/v1/assessments/{id}/answers` as idempotent upsert by `(assessment_id, question_id)` and document retry-safe behavior for auto-save clients.
- Consider optimistic concurrency (e.g., `updated_at` precondition or revision number) if multi-tab edits are expected.

## Testing Strategy
- **Unit tests**: Difficulty distribution computation for various `question_count` values (verify sum equals count), interleaved shuffle produces mixed ordering, format distribution calculation.
- **Integration tests**: Full assessment creation with pre-seeded pools and questions, question selection excludes previously seen questions, answer upsert (create then update), assessment completion lifecycle.
- **Edge case tests**: Competency with very small `question_count` (e.g., 4) still distributes across difficulty levels, insufficient questions in a bucket triggers fallback, user with extensive history still gets 100 unique questions.
- **Determinism test**: Given the same random seed, question selection produces the same result.

## Acceptance Criteria
- [ ] Assessment creation selects exactly 100 questions.
- [ ] Question counts per competency match `role_competency_weights.question_count` for the user's role.
- [ ] Difficulty distribution follows the bell curve (10/20/35/25/10) within each competency's allocation.
- [ ] Previously seen questions (in `user_question_history`) are excluded.
- [ ] Selected questions are recorded in `user_question_history` after assembly.
- [ ] Final question order is interleaved (not grouped by competency or format).
- [ ] Answer submission supports upsert: auto-save does not overwrite a manual submission.
- [ ] `time_spent_seconds` is tracked per answer.
- [ ] Assessment status transitions from `in_progress` to `completed` on submission.
- [ ] Completed assessments reject new answer submissions (400 error).
- [ ] Question responses sent to the client do not include `correct_answer` or `grading_rubric`.
- [ ] Assessment creation is atomic: partial failures roll back completely.
