# SPEC-032: Results Computation Engine

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-030 (MCQ auto-grading)
- SPEC-031 (AI grading for open-ended questions)

## Overview
After all individual answers have been graded (both MCQ auto-grading and AI grading), compute aggregate results: per-competency weighted scores, overall assessment score, proficiency level classifications, and total time spent. This engine transforms raw `AnswerGrade` records into meaningful `CompetencyScore` and `AssessmentResult` summaries that drive the results visualization.

## Requirements

### Functional
1. When all `AnswerGrade` records for an assessment exist (`grading_status = "grading"`), trigger results computation
2. For each of the 12 competencies, compute a weighted score:
   - Gather all graded answers for questions in that competency
   - Separate MCQ grades (`grading_method = "auto"`) and AI grades (`grading_method = "ai"`)
   - MCQ score: count of correct / total MCQ questions in that competency (yields 0.0-1.0)
   - AI score: average of all AI grade scores in that competency (already 0.0-1.0)
   - Combined competency score: weighted blend of MCQ and AI scores based on the number of questions of each type, then scaled to 0-100
3. Create a `CompetencyScore` record for each competency with:
   - `score`: the computed 0-100 score
   - `proficiency_level`: integer 0-4 based on score thresholds
   - `questions_total`: total questions for that competency
   - `questions_correct`: count of MCQ correct answers
   - `ai_graded_avg`: average AI grade score (nullable if no AI questions)
4. Compute overall assessment score as a weighted average of competency scores using `RoleCompetencyWeight.weight` for the user's `primary_role`
5. Map scores to proficiency levels using these thresholds:
   - 0-20: level 0 = "novice"
   - 21-40: level 1 = "beginner"
   - 41-60: level 2 = "intermediate"
   - 61-80: level 3 = "advanced"
   - 81-100: level 4 = "expert"
6. Calculate `total_time_seconds` by summing `Answer.time_spent_seconds` across all answers
7. Update `AssessmentResult` with:
   - `overall_score`
   - `overall_proficiency_level`
   - `proficiency_label`
   - `total_time_seconds`
   - `grading_status = "complete"`

### Non-Functional
1. Results computation must complete in under 1 second for a 100-question assessment
2. Computation is idempotent: re-running produces the same results and overwrites existing `CompetencyScore` records
3. Computation must handle edge cases: competencies with zero questions, all-unanswered assessments, missing role weights

## Technical Design

### Service Layer
Add to `src/scoring/service.py`:

```python
async def compute_results(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AssessmentResult:
    """Compute aggregate results from individual answer grades."""

def compute_competency_score(
    mcq_grades: list[AnswerGrade],
    ai_grades: list[AnswerGrade],
) -> float:
    """Compute a single competency's 0-100 score from its grades."""

def score_to_proficiency(score: float) -> tuple[int, str]:
    """Map a 0-100 score to (level_int, label_string)."""
```

### Computation Algorithm
```
for each competency (1-12):
    mcq_grades = [g for g in grades if g.question.format == "multiple_choice" and g.question.competency_id == c]
    ai_grades  = [g for g in grades if g.question.format != "multiple_choice" and g.question.competency_id == c]

    mcq_score = sum(g.score for g in mcq_grades) / len(mcq_grades) if mcq_grades else 0
    ai_score  = sum(g.score for g in ai_grades) / len(ai_grades) if ai_grades else 0

    total = len(mcq_grades) + len(ai_grades)
    if total > 0:
        competency_score = ((mcq_score * len(mcq_grades) + ai_score * len(ai_grades)) / total) * 100
    else:
        competency_score = 0

    create CompetencyScore(score=competency_score, ...)

overall_score = sum(cs.score * weight.weight for cs, weight in zip(competency_scores, role_weights))
              / sum(weight.weight for weight in role_weights)
```

### Proficiency Level Mapping
```python
PROFICIENCY_THRESHOLDS = [
    (0, 20, 0, "novice"),
    (21, 40, 1, "beginner"),
    (41, 60, 2, "intermediate"),
    (61, 80, 3, "advanced"),
    (81, 100, 4, "expert"),
]

def score_to_proficiency(score: float) -> tuple[int, str]:
    for low, high, level, label in PROFICIENCY_THRESHOLDS:
        if low <= score <= high:
            return level, label
    return 0, "novice"
```

### Database Queries
- Join `answer_grades` with `answers`, `assessment_questions`, and `questions` to get grade + competency mapping in a single query
- Fetch `RoleCompetencyWeight` rows for the user's `primary_role` from `user_profiles`
- Upsert `CompetencyScore` rows using `on_conflict_do_update` on `(result_id, competency_id)` for idempotency

### Database Changes
- Add a unique constraint on `competency_scores(result_id, competency_id)` if not already present, to support upsert behavior

## Implementation Notes
- The weighted average formula must handle the case where a role has no weight defined for a competency (use weight 0, effectively excluding it)
- If a user's `primary_role` is not found in `RoleCompetencyWeight`, fall back to the `"fullstack"` role weights as a sensible default
- Score values should be rounded to 2 decimal places for consistency
- The computation should be triggered automatically after the last AI grade is persisted, not via a separate API call
- Edge case: if all answers are unanswered, the overall score is 0 and proficiency is "novice"

## Testing Strategy
- Unit tests for: `compute_competency_score` with various MCQ/AI grade combinations, `score_to_proficiency` for all threshold boundaries (0, 20, 21, 40, 41, 60, 61, 80, 81, 100), weighted average calculation with different role weights, edge cases (empty grades, single question, all incorrect)
- Integration tests for: full computation flow from grades to `CompetencyScore` and `AssessmentResult` records, idempotency (run twice, check no duplicates), fallback role weights
- E2E tests for: N/A (computation is backend-only)

## Acceptance Criteria
- [ ] `CompetencyScore` records are created for all 12 competencies after grading completes
- [ ] Competency scores correctly blend MCQ and AI grades proportionally
- [ ] Scores are on a 0-100 scale, rounded to 2 decimal places
- [ ] Proficiency levels map correctly at all threshold boundaries
- [ ] Overall score uses role-specific weights from `RoleCompetencyWeight`
- [ ] `total_time_seconds` sums all individual answer times
- [ ] `AssessmentResult` is updated with overall score, proficiency level, label, and time
- [ ] `grading_status` transitions to `"complete"` after computation
- [ ] Computation handles competencies with zero questions gracefully
- [ ] Re-running computation on the same assessment produces identical results
- [ ] Missing role weights fall back to "fullstack" defaults
