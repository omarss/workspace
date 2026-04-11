# SPEC-031: AI Grading for Open-Ended Questions

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-012 (Question generation via Claude)
- SPEC-030 (MCQ auto-grading)

## Overview
Implement AI-powered grading for open-ended question formats (code_review, debugging, short_answer, design_prompt) using Claude Opus. Each answer is evaluated against the question's `grading_rubric`, producing a normalized score (0.0-1.0), structured rubric breakdown, and constructive feedback. Because AI grading is slower than MCQ auto-grading, it runs as a background task with progress tracking and retry logic.

## Requirements

### Functional
1. After MCQ auto-grading completes (`grading_status = "auto_complete"`), enqueue AI grading for all non-MCQ answers
2. For each open-ended answer, send the question body, code snippet (if any), grading rubric, and user's response to Claude Opus for evaluation
3. Claude must return a structured response containing:
   - `score`: float between 0.0 and 1.0
   - `rubric_breakdown`: object mapping each rubric criterion to its individual score and reasoning
   - `feedback`: constructive, actionable feedback text (2-5 sentences)
   - `is_correct`: null (not applicable for open-ended questions)
4. Create an `AnswerGrade` record per open-ended answer with:
   - `grading_method = "ai"`
   - `score`, `feedback`, `rubric_breakdown` from Claude's response
   - `is_correct = None`
5. Track grading progress via `AssessmentResult.grading_status`:
   - `"pending"` - assessment not yet completed
   - `"grading"` - MCQ done, AI grading in progress
   - `"auto_complete"` - MCQ grading done, AI not yet started
   - `"complete"` - all grading finished
6. Provide a polling endpoint `GET /api/v1/results/{assessment_id}/grading-status` returning total to grade, graded count, and progress percentage
7. Handle unanswered open-ended questions with `score = 0.0` and feedback indicating no response was provided
8. If Claude API is unavailable, queue the answer for retry with exponential backoff (initial delay 5s, max delay 5min, max retries 5)

### Non-Functional
1. AI grading should complete within 60 seconds for a typical assessment (~30-50 open-ended questions)
2. Concurrent grading: process up to 5 answers in parallel to maximize throughput
3. Individual grading calls must timeout after 30 seconds
4. Token usage should be logged for cost monitoring
5. Claude responses must be validated against expected schema before persisting

## Technical Design

### API Endpoints
- `GET /api/v1/results/{assessment_id}/grading-status` - Returns grading progress (already scaffolded in router)

### Service Layer
Add to `src/scoring/service.py`:

```python
async def grade_open_ended(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Grade all open-ended answers for an assessment using Claude Opus."""

async def grade_single_answer(
    db: AsyncSession,
    answer: Answer,
    question: Question,
) -> AnswerGrade:
    """Grade a single open-ended answer via Claude API."""
```

### Claude API Integration
Add `src/scoring/grader.py`:

```python
class AIGrader:
    """Handles communication with Claude Opus for answer evaluation."""

    async def grade(
        self,
        question_body: str,
        code_snippet: str | None,
        rubric: dict,
        student_response: str,
        question_format: str,
    ) -> GradeResult:
        """Send answer to Claude for grading. Returns structured result."""
```

### Prompt Design
The grading prompt should include:
- System prompt establishing Claude as an expert software engineering evaluator
- The full question body and code snippet
- The grading rubric with criteria and point allocations
- The student's response
- Explicit output format instructions (JSON with `score`, `rubric_breakdown`, `feedback`)
- Instruction to be constructive, specific, and fair

### Retry Logic
```python
class GradingRetryPolicy:
    initial_delay: float = 5.0
    max_delay: float = 300.0  # 5 minutes
    max_retries: int = 5
    backoff_factor: float = 2.0
```

On failure:
1. Log the error with answer_id and attempt number
2. Wait for `min(initial_delay * backoff_factor ** attempt, max_delay)` seconds
3. After max retries, mark the grade with `score = 0.0` and `feedback = "Grading temporarily unavailable. This answer will be re-evaluated."`
4. Set a `grading_failed` flag on the `AssessmentResult` for admin review

### Background Processing
Use `asyncio.create_task` during the request lifecycle or a background task runner:
1. After `auto_grade_mcq` completes, spawn the AI grading task
2. The grading task processes answers in batches of 5 using `asyncio.gather` with `return_exceptions=True`
3. Each batch updates progress in the database before moving to the next

### Response Validation
```python
class GradeResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    rubric_breakdown: dict[str, RubricCriterionResult]
    feedback: str = Field(min_length=10, max_length=2000)

class RubricCriterionResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str
```

## Implementation Notes
- Use `anthropic` Python SDK with `async` client for non-blocking API calls
- Set `max_tokens = 1024` for grading responses to control costs
- Parse Claude's response as JSON; if parsing fails, retry once with a more explicit format instruction
- Log all Claude API calls with request/response sizes and latencies for cost analysis
- The grading prompt should vary slightly by `question_format` to provide appropriate evaluation context (e.g., code_review questions should emphasize code quality assessment, design_prompt should emphasize architectural thinking)
- Consider caching the Anthropic client instance at module level to reuse connections

## Testing Strategy
- Unit tests for: prompt construction per question format, response parsing and validation, retry logic with mock failures, score normalization, unanswered question handling
- Integration tests for: full grading flow with mocked Claude API, grading status transitions, progress tracking accuracy, concurrent grading batches
- E2E tests for: grading-status polling endpoint returning correct progress

## Acceptance Criteria
- [ ] All open-ended answers receive an `AnswerGrade` with `grading_method = "ai"`
- [ ] AI grades include a `score` between 0.0 and 1.0
- [ ] AI grades include a `rubric_breakdown` with per-criterion scores and reasoning
- [ ] AI grades include constructive `feedback` text
- [ ] `grading_status` transitions through `auto_complete` -> `grading` -> `complete`
- [ ] Polling endpoint returns accurate progress percentage
- [ ] Failed Claude API calls retry with exponential backoff up to 5 times
- [ ] After max retries, a fallback grade is created and the result is flagged
- [ ] Unanswered open-ended questions receive `score = 0.0`
- [ ] AI grading processes answers concurrently (up to 5 in parallel)
- [ ] Individual grading calls timeout after 30 seconds
- [ ] Claude API token usage is logged per grading session
