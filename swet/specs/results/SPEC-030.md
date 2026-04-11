# SPEC-030: MCQ Auto-Grading

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-014 (Assessment engine)
- SPEC-015 (Question format specifications)

## Overview
Implement instant, deterministic grading for multiple-choice questions (MCQ) by comparing the user's `selected_option` against the question's `correct_answer`. This is the simplest grading path and runs synchronously when an assessment is completed, producing an `AnswerGrade` record for every MCQ answer before any AI grading begins.

## Requirements

### Functional
1. When an assessment transitions to `completed` status, trigger auto-grading for all MCQ answers in that assessment
2. For each MCQ answer, compare `Answer.selected_option` against `Question.correct_answer` (case-insensitive, trimmed)
3. Create an `AnswerGrade` record per MCQ answer with:
   - `grading_method = "auto"`
   - `is_correct = True/False` based on the comparison
   - `score = 1.0` if correct, `score = 0.0` if incorrect
   - `feedback = None` (MCQ answers do not receive written feedback)
   - `rubric_breakdown = None`
4. Handle unanswered MCQ questions (no `Answer` row or `selected_option` is null) by creating a grade with `is_correct = False`, `score = 0.0`
5. Auto-grading must be idempotent: re-running on the same assessment does not create duplicate grades
6. After all MCQ grades are created, update the `AssessmentResult.grading_status` to `"auto_complete"` (signaling AI grading can begin)

### Non-Functional
1. Auto-grading for 100 questions must complete in under 500ms (database round-trips only, no external calls)
2. Grading runs within a single database transaction to ensure atomicity
3. If auto-grading fails mid-way, no partial grades are persisted (transaction rollback)

## Technical Design

### Service Layer
Add to `src/scoring/service.py`:

```python
async def auto_grade_mcq(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    """Auto-grade all MCQ answers for a completed assessment.

    Returns the number of MCQ answers graded.
    """
```

**Algorithm:**
1. Fetch all `AssessmentQuestion` rows for the assessment, joined with `Question` to get `format` and `correct_answer`
2. Filter to MCQ-format questions only (`format = "multiple_choice"`)
3. Fetch all `Answer` rows for the assessment, indexed by `question_id`
4. For each MCQ question:
   - Look up the corresponding answer (may be missing)
   - Check if an `AnswerGrade` already exists for this answer (idempotency)
   - Compare `selected_option` vs `correct_answer`
   - Insert `AnswerGrade` record
5. Return count of graded answers

### Integration Point
The `complete_assessment` function in `src/assessments/service.py` should call `auto_grade_mcq` after setting `status = "completed"`. This creates the `AssessmentResult` record and triggers auto-grading in the same request cycle.

```python
async def complete_assessment(db, assessment_id, user_id):
    assessment = await get_assessment(db, assessment_id, user_id)
    assessment.status = "completed"
    assessment.completed_at = datetime.now(timezone.utc)

    # Create result record
    result = AssessmentResult(
        assessment_id=assessment_id,
        user_id=user_id,
        grading_status="pending",
    )
    db.add(result)
    await db.flush()

    # Auto-grade MCQs synchronously
    await auto_grade_mcq(db, assessment_id, user_id)

    result.grading_status = "auto_complete"
    await db.flush()
    return assessment
```

### Database Queries
- Bulk insert `AnswerGrade` rows using `insert(...).on_conflict_do_nothing()` on the `answer_id` unique constraint for idempotency
- Single query to join `assessment_questions`, `questions`, and `answers` to minimize round-trips

## Implementation Notes
- MCQ comparison must be case-insensitive and whitespace-trimmed: `selected.strip().lower() == correct.strip().lower()`
- Questions without a `correct_answer` value should be logged as warnings and skipped (defensive coding against bad seed data)
- The grading trigger lives in the assessment completion flow, not in a separate background task, because MCQ grading is fast enough for synchronous execution
- Consider using `bulk_save_objects` or `add_all` for batch insertion performance

## Testing Strategy
- Unit tests for: comparison logic (exact match, case mismatch, whitespace, null answer, null correct_answer), idempotency (running twice produces same results), unanswered question handling
- Integration tests for: full assessment completion triggering auto-grading, correct `AnswerGrade` records in the database, `grading_status` transition from `"pending"` to `"auto_complete"`
- E2E tests for: N/A (grading is backend-only at this stage)

## Acceptance Criteria
- [ ] Completing an assessment creates `AnswerGrade` records for all MCQ answers
- [ ] Correct answers receive `score = 1.0` and `is_correct = True`
- [ ] Incorrect answers receive `score = 0.0` and `is_correct = False`
- [ ] Unanswered MCQ questions receive `score = 0.0` and `is_correct = False`
- [ ] All MCQ grades have `grading_method = "auto"`
- [ ] Re-completing or re-grading does not create duplicate `AnswerGrade` rows
- [ ] `AssessmentResult.grading_status` is `"auto_complete"` after MCQ grading finishes
- [ ] Auto-grading for 100 MCQ questions completes in under 500ms
- [ ] A failed grading run does not leave partial grades in the database
