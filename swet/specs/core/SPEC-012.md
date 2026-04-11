# SPEC-012: Question Generation via Claude

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-005 (API error handling and response format)
- SPEC-011 (Competency and role definitions)

## Overview
SWET generates assessment questions dynamically using Claude Sonnet (Anthropic API). Questions are generated in batches for a specific combination of competency, difficulty level, and question format. The generation system uses structured JSON output, role-specific prompt engineering, and retry logic to produce high-quality, consistent questions across 5 formats.

Generated questions are stored in question pools (SPEC-013) and reused across users with the same `config_hash`. This spec covers the prompt design, API interaction, output parsing, and error handling for the generation pipeline.

## Requirements

### Functional
1. Questions are generated using Claude Sonnet (model: `claude-sonnet-4-20250514` or latest) via the Anthropic Python SDK.
2. Each generation request produces approximately 20 questions for a single `(competency, difficulty, format)` bucket.
3. Five question formats are supported, with the following distribution per assessment:
   - **MCQ** (multiple choice): 40% of questions
   - **Code Review**: 15% of questions
   - **Debugging**: 15% of questions
   - **Short Answer**: 15% of questions
   - **Design Prompt**: 15% of questions
4. Five difficulty levels are used: L1 (beginner), L2 (intermediate), L3 (advanced), L4 (expert), L5 (principal).
5. Claude responses must conform to a predefined JSON schema. The prompt instructs the model to return a JSON array of question objects.
6. Each generated question includes a grading rubric (for non-MCQ formats) or a correct answer (for MCQ).
7. Generation includes role-specific context: the user's primary role and technology stack are embedded in the prompt to make questions relevant.
8. Failed API calls are retried with exponential backoff using `tenacity` (max 3 attempts, 2s/4s/8s waits).
9. If all retries fail, the question pool is marked as `failed` and an error is logged.
10. Questions must be unique within a pool: no duplicate titles or near-identical content.

### Non-Functional
1. A single generation call (20 questions) should complete in under 60 seconds.
2. Prompt token usage should be monitored and logged for cost tracking.
3. The generation module must be testable with mocked API responses (no real Claude calls in tests).
4. Structured output validation rejects malformed responses before persisting.

## Technical Design

### Generation Pipeline
```
trigger_generation(config_hash, competency_id, difficulty, format)
  -> build_prompt(competency, difficulty, format, role_context)
  -> call_claude_api(prompt) [with tenacity retry]
  -> parse_and_validate(response, schema)
  -> store_questions(pool_id, questions)
  -> update_pool_status("complete")
```

### Prompt Structure

Each prompt consists of:
1. **System message**: Defines Claude's role as an expert software engineering assessment author. Instructs structured JSON output.
2. **User message**: Contains the specific generation request with:
   - Competency name and description
   - Difficulty level with calibration guidance
   - Question format with structural requirements
   - Role context (primary role, languages, frameworks)
   - Number of questions to generate (20)
   - Output JSON schema

#### Difficulty Calibration Guide (embedded in prompt)
| Level | Label | Target Audience | Characteristics |
|---|---|---|---|
| L1 | Beginner | 0-1 years | Fundamental concepts, syntax-level knowledge |
| L2 | Intermediate | 1-3 years | Applied knowledge, common patterns |
| L3 | Advanced | 3-6 years | Nuanced trade-offs, edge cases, architectural reasoning |
| L4 | Expert | 6-10 years | Complex system interactions, production-grade considerations |
| L5 | Principal | 10+ years | Strategic technical decisions, cross-cutting concerns, mentoring-level depth |

#### Format-Specific Prompt Instructions
- **MCQ**: Generate 4 options (A/B/C/D) with exactly one correct answer. Distractors should be plausible. Include explanation for why the correct answer is right and others are wrong.
- **Code Review**: Provide a code snippet (20-80 lines) in a specified language with intentional issues. The prompt asks the candidate to identify problems and suggest improvements.
- **Debugging**: Present a scenario with error output, logs, or stack traces. The candidate must identify root cause, provide a fix, and suggest prevention measures.
- **Short Answer**: Pose a conceptual or scenario-based question requiring a written explanation (target 100-300 words).
- **Design Prompt**: Describe a system or feature to design, asking for architecture, components, trade-offs, and scalability considerations.

### Expected JSON Output Schema (per question)
```json
{
  "title": "string (concise question title, max 200 chars)",
  "body": "string (full question in markdown)",
  "code_snippet": "string | null (for code_review/debugging formats)",
  "language": "string | null (programming language of snippet)",
  "options": {
    "A": "string",
    "B": "string",
    "C": "string",
    "D": "string"
  },
  "correct_answer": "string (A/B/C/D for MCQ, null for others)",
  "grading_rubric": {
    "criteria": [
      {
        "name": "string",
        "description": "string",
        "max_points": "number",
        "key_indicators": ["string"]
      }
    ],
    "max_score": "number",
    "passing_threshold": "number"
  },
  "explanation": "string (detailed explanation of expected answer)",
  "metadata": {
    "topics": ["string"],
    "estimated_time_minutes": "number"
  }
}
```

### API Client Module (`src/questions/generator.py`)
```python
async def generate_questions(
    competency: Competency,
    difficulty: int,
    format: str,
    role_context: dict,  # {role, languages, frameworks}
    count: int = 20,
) -> list[dict]:
    """Generate questions via Claude API with retry logic."""
```

### Retry Configuration (tenacity)
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type((APIConnectionError, APITimeoutError)),
    before_sleep=log_retry_attempt,
)
async def _call_claude(prompt: str, system: str) -> str:
    ...
```

### Components
- `src/questions/generator.py` - Core generation logic, prompt building, API calls.
- `src/questions/prompts.py` - Prompt templates and format-specific instructions.
- `src/questions/schemas.py` - Pydantic models for validating Claude's JSON output.

## Implementation Notes
- Claude Sonnet is used (not Opus) for generation because it provides sufficient quality at lower cost and latency. Opus is reserved for grading (SPEC-031).
- The prompt explicitly requests JSON output and includes the schema in the instructions. If Claude returns malformed JSON, the response is rejected and retried.
- Role context is injected to ensure questions reference relevant technologies (e.g., a Python backend developer gets Python code snippets, not Java).
- The `metadata.estimated_time_minutes` field helps the frontend display time guidance but is not enforced.
- Each format has different nullable fields: MCQ uses `options` and `correct_answer`, code-based formats use `code_snippet` and `language`, all non-MCQ formats use `grading_rubric`.
- Token usage should be logged per generation call for cost monitoring. Consider storing in a `generation_logs` table in future iterations.

## Testing Strategy
- **Unit tests**: Prompt builder produces correct format-specific instructions, JSON validation correctly accepts/rejects sample responses, retry logic triggers on transient errors.
- **Integration tests**: Mock the Anthropic client and verify the full pipeline (prompt -> API call -> parse -> store) works end-to-end. Test with realistic mock responses for each of the 5 formats.
- **Contract tests**: Validate generated question JSON against the expected schema for each format.
- **Manual/staging tests**: Run actual generation against Claude API in a staging environment to validate question quality and prompt effectiveness.

## Acceptance Criteria
- [ ] Generation produces ~20 valid questions per `(competency, difficulty, format)` call.
- [ ] All 5 question formats are supported with format-specific prompt instructions.
- [ ] Claude responses are validated against the expected JSON schema before storage.
- [ ] Malformed responses are rejected and the call is retried (up to 3 attempts).
- [ ] Transient API errors (connection, timeout) trigger exponential backoff retry.
- [ ] Permanent API errors (auth, rate limit) fail immediately and mark the pool as `failed`.
- [ ] Role context (role, languages, frameworks) is included in every generation prompt.
- [ ] Difficulty calibration produces noticeably different question complexity across L1-L5.
- [ ] MCQ questions have exactly 4 options with one correct answer.
- [ ] Non-MCQ questions include a grading rubric with criteria and point allocations.
- [ ] The generator module is fully testable with mocked API responses.
