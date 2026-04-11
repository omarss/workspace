# SPEC-015: Question Format Specifications

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-012 (Question generation via Claude)

## Overview
SWET supports 5 question formats, each designed to assess different dimensions of software engineering competency. This spec defines the detailed structure, JSON schemas, rendering requirements, response schemas, and grading rubric formats for each question type. These schemas serve as the contract between the question generator (SPEC-012), the question renderer components (SPEC-020), and the grading engines (SPEC-030/031).

## Requirements

### Functional
1. Five question formats are supported: `mcq`, `code_review`, `debugging`, `short_answer`, and `design_prompt`.
2. Each format has a well-defined JSON schema for both the question structure (stored in DB) and the expected response structure (submitted by the user).
3. MCQ is the only auto-gradable format. The other 4 formats require AI grading.
4. All question bodies support markdown rendering (headings, bold, code blocks, lists).
5. Each non-MCQ format includes a grading rubric with named criteria, point allocations, and key indicators for the AI grader.
6. Format-specific fields (`options`, `code_snippet`, `correct_answer`) are nullable: only the fields relevant to each format are populated.

### Non-Functional
1. Question body markdown must render correctly in the frontend without XSS vulnerabilities (sanitized rendering).
2. Code snippets must support syntax highlighting for all 14 supported languages.
3. Response schemas must be validatable on both frontend (TypeScript) and backend (Pydantic).

## Technical Design

### Format 1: Multiple Choice (MCQ)

#### Purpose
Tests factual knowledge, conceptual understanding, and pattern recognition. Efficient for breadth coverage across competencies.

#### Question Schema
```json
{
  "format": "mcq",
  "title": "What is the primary purpose of database indexing?",
  "body": "Consider a PostgreSQL table with 10 million rows...\n\nWhich of the following best describes...",
  "code_snippet": null,
  "language": null,
  "options": {
    "A": "To reduce disk space usage by compressing table data",
    "B": "To speed up data retrieval by creating a sorted reference structure",
    "C": "To enforce data integrity constraints between tables",
    "D": "To automatically partition large tables across multiple disks"
  },
  "correct_answer": "B",
  "grading_rubric": null,
  "explanation": "Database indexes create a B-tree (or similar) structure that allows the query planner to locate rows without scanning the entire table...",
  "metadata": {
    "topics": ["databases", "indexing", "performance"],
    "estimated_time_minutes": 1
  }
}
```

#### Response Schema
```json
{
  "selected_option": "B"
}
```

#### Grading
- Auto-graded by exact match: `selected_option == correct_answer`.
- Score: 1.0 (correct) or 0.0 (incorrect). No partial credit.

---

### Format 2: Code Review

#### Purpose
Tests ability to read, analyze, and critique code. Assesses understanding of best practices, common pitfalls, and improvement strategies.

#### Question Schema
```json
{
  "format": "code_review",
  "title": "Review this Python authentication middleware",
  "body": "Review the following authentication middleware implementation. Identify any issues related to security, performance, error handling, and code quality. Suggest specific improvements for each issue found.",
  "code_snippet": "class AuthMiddleware:\n    def __init__(self, secret_key):\n        self.secret = secret_key\n    \n    async def __call__(self, request, call_next):\n        token = request.headers.get('Authorization')\n        if token:\n            try:\n                payload = jwt.decode(token, self.secret)\n                request.state.user = payload\n            except:\n                pass\n        response = await call_next(request)\n        return response",
  "language": "python",
  "options": null,
  "correct_answer": null,
  "grading_rubric": {
    "criteria": [
      {
        "name": "Issue Identification",
        "description": "Correctly identifies security, performance, and quality issues in the code",
        "max_points": 4,
        "key_indicators": [
          "Identifies bare except clause",
          "Notes missing Bearer prefix stripping",
          "Identifies lack of token expiry validation",
          "Notes missing algorithm specification in jwt.decode"
        ]
      },
      {
        "name": "Improvement Quality",
        "description": "Provides actionable, specific improvements for identified issues",
        "max_points": 3,
        "key_indicators": [
          "Suggests specific exception types to catch",
          "Provides corrected code or pseudocode",
          "Addresses security implications"
        ]
      },
      {
        "name": "Depth of Analysis",
        "description": "Goes beyond surface-level observations to explain impact and reasoning",
        "max_points": 3,
        "key_indicators": [
          "Explains why bare except is dangerous",
          "Discusses production implications",
          "Considers edge cases"
        ]
      }
    ],
    "max_score": 10,
    "passing_threshold": 5
  },
  "explanation": "Key issues: 1) Bare except swallows all errors silently...",
  "metadata": {
    "topics": ["security", "middleware", "jwt", "error-handling"],
    "estimated_time_minutes": 5
  }
}
```

#### Response Schema
```json
{
  "response_text": "## Issues Found\n\n### 1. Security: Bare except clause\nThe `except: pass` silently swallows all exceptions..."
}
```

#### Grading
- AI-graded (Claude Opus) against the rubric criteria.
- Score: sum of criteria scores / `max_score`, normalized to 0.0-1.0.

---

### Format 3: Debugging

#### Purpose
Tests systematic debugging methodology: reading error output, identifying root causes, proposing fixes, and suggesting prevention measures.

#### Question Schema
```json
{
  "format": "debugging",
  "title": "Debug this async connection pool exhaustion",
  "body": "A production FastAPI application is intermittently returning 503 errors under moderate load. The following error appears in the logs. Identify the root cause, provide a fix, and suggest how to prevent similar issues.",
  "code_snippet": "# Application code\nasync def get_user(user_id: int):\n    async with get_db_connection() as conn:\n        result = await conn.execute(\n            'SELECT * FROM users WHERE id = $1', user_id\n        )\n        user = await result.fetchone()\n        if not user:\n            raise HTTPException(404)\n        # Process user data\n        enriched = await enrich_user_data(user)\n        return enriched\n\n# Error log\nTraceback (most recent call last):\n  asyncpg.exceptions.TooManyConnectionsError:\n    cannot open new connection: too many connections (max: 20)\n\n# Metrics\n  Active connections: 20/20\n  Average response time: 450ms -> 12000ms (spike)\n  Request rate: 150 req/s",
  "language": "python",
  "options": null,
  "correct_answer": null,
  "grading_rubric": {
    "criteria": [
      {
        "name": "Root Cause Identification",
        "description": "Correctly identifies the root cause of the issue",
        "max_points": 4,
        "key_indicators": [
          "Identifies that enrich_user_data runs inside the connection context",
          "Explains connection is held during external/slow operations",
          "Recognizes connection pool starvation pattern"
        ]
      },
      {
        "name": "Fix Quality",
        "description": "Provides a correct and complete fix",
        "max_points": 3,
        "key_indicators": [
          "Moves enrich_user_data outside the connection context",
          "Suggests connection pool size tuning",
          "Fix is syntactically correct"
        ]
      },
      {
        "name": "Prevention Strategy",
        "description": "Suggests measures to prevent recurrence",
        "max_points": 3,
        "key_indicators": [
          "Recommends connection timeout configuration",
          "Suggests connection pool monitoring/alerting",
          "Mentions connection lifetime limits or health checks"
        ]
      }
    ],
    "max_score": 10,
    "passing_threshold": 5
  },
  "explanation": "The root cause is connection pool exhaustion...",
  "metadata": {
    "topics": ["async", "connection-pooling", "debugging", "production"],
    "estimated_time_minutes": 7
  }
}
```

#### Response Schema
```json
{
  "response_text": "## Root Cause\nThe connection pool is being exhausted because...\n\n## Fix\n```python\nasync def get_user(user_id: int):\n    async with get_db_connection() as conn:\n        result = await conn.execute(...)\n        user = await result.fetchone()\n    # Process outside connection context\n    enriched = await enrich_user_data(user)\n    return enriched\n```\n\n## Prevention\n1. Configure connection pool timeouts..."
}
```

#### Grading
- AI-graded against the 3-part rubric (root cause, fix, prevention).
- Score: sum of criteria scores / `max_score`, normalized to 0.0-1.0.

---

### Format 4: Short Answer

#### Purpose
Tests conceptual depth and ability to explain technical concepts clearly. Assesses communication skills alongside technical knowledge.

#### Question Schema
```json
{
  "format": "short_answer",
  "title": "Explain the CAP theorem and its practical implications",
  "body": "Explain the CAP theorem in distributed systems. For each of the three guarantees (Consistency, Availability, Partition tolerance), provide:\n\n1. A clear definition\n2. A real-world system that prioritizes it\n3. The trade-off involved when choosing to prioritize it\n\nAim for 150-300 words.",
  "code_snippet": null,
  "language": null,
  "options": null,
  "correct_answer": null,
  "grading_rubric": {
    "criteria": [
      {
        "name": "Conceptual Accuracy",
        "description": "Correctly defines the CAP theorem and its three guarantees",
        "max_points": 4,
        "key_indicators": [
          "Correct definition of Consistency (all nodes see same data at same time)",
          "Correct definition of Availability (every request receives a response)",
          "Correct definition of Partition tolerance (system operates despite network partitions)",
          "States that only 2 of 3 can be fully guaranteed simultaneously"
        ]
      },
      {
        "name": "Practical Examples",
        "description": "Provides relevant real-world examples for each guarantee",
        "max_points": 3,
        "key_indicators": [
          "Appropriate CP example (e.g., HBase, MongoDB with majority read)",
          "Appropriate AP example (e.g., Cassandra, DynamoDB)",
          "Examples are accurate and well-explained"
        ]
      },
      {
        "name": "Trade-off Analysis",
        "description": "Demonstrates understanding of the trade-offs involved",
        "max_points": 3,
        "key_indicators": [
          "Explains impact of sacrificing each guarantee",
          "Discusses practical considerations beyond theory",
          "Shows nuanced understanding (e.g., PACELC extension)"
        ]
      }
    ],
    "max_score": 10,
    "passing_threshold": 5
  },
  "explanation": "The CAP theorem states that a distributed system cannot simultaneously provide...",
  "metadata": {
    "topics": ["distributed-systems", "cap-theorem", "trade-offs"],
    "estimated_time_minutes": 5
  }
}
```

#### Response Schema
```json
{
  "response_text": "The CAP theorem, formulated by Eric Brewer, states that..."
}
```

#### Grading
- AI-graded against the rubric criteria.
- Character guidance (150-300 words) is advisory, not enforced. Extremely short responses may score lower on depth criteria.

---

### Format 5: Design Prompt

#### Purpose
Tests system design thinking, architectural decision-making, and ability to reason about trade-offs at scale. Assesses senior-level engineering judgment.

#### Question Schema
```json
{
  "format": "design_prompt",
  "title": "Design a real-time notification system",
  "body": "Design a notification system for a social media platform with 50 million daily active users. The system must support:\n\n- Push notifications (mobile)\n- In-app notifications (web)\n- Email digests\n- User notification preferences\n\nAddress the following areas in your response:\n\n1. **Architecture**: High-level system architecture and key components\n2. **Data Model**: Core entities and their relationships\n3. **Trade-offs**: Key design decisions and their trade-offs\n4. **Scalability**: How the system handles growth and peak loads",
  "code_snippet": null,
  "language": null,
  "options": null,
  "correct_answer": null,
  "grading_rubric": {
    "criteria": [
      {
        "name": "Architecture",
        "description": "Proposes a sound, scalable architecture with appropriate components",
        "max_points": 4,
        "key_indicators": [
          "Identifies need for message queue/event bus",
          "Separates notification creation from delivery",
          "Includes fan-out strategy for social graph",
          "Considers multi-channel delivery abstraction"
        ]
      },
      {
        "name": "Data Model",
        "description": "Designs an effective data model for notifications and preferences",
        "max_points": 2,
        "key_indicators": [
          "Notification entity with status tracking",
          "User preference model (per-channel, per-type)",
          "Appropriate storage choices (SQL vs NoSQL for different data)"
        ]
      },
      {
        "name": "Trade-off Analysis",
        "description": "Identifies and evaluates key design trade-offs",
        "max_points": 2,
        "key_indicators": [
          "Push vs pull delivery model trade-offs",
          "Consistency vs latency for notification delivery",
          "Batch vs real-time processing for different channels"
        ]
      },
      {
        "name": "Scalability",
        "description": "Addresses scaling challenges and proposes solutions",
        "max_points": 2,
        "key_indicators": [
          "Horizontal scaling strategy",
          "Handling thundering herd / viral content spikes",
          "Rate limiting and backpressure mechanisms"
        ]
      }
    ],
    "max_score": 10,
    "passing_threshold": 5
  },
  "explanation": "A well-designed notification system at this scale requires...",
  "metadata": {
    "topics": ["system-design", "notifications", "scalability", "architecture"],
    "estimated_time_minutes": 10
  }
}
```

#### Response Schema
```json
{
  "response_text": "## Architecture\n\nThe notification system follows an event-driven architecture...\n\n## Data Model\n\n### Core Entities\n- `Notification`: id, user_id, type, channel, payload, status...\n\n## Trade-offs\n\n### Push vs Pull\n...\n\n## Scalability\n..."
}
```

#### Grading
- AI-graded against the multi-dimensional rubric.
- Each area (architecture, data model, trade-offs, scalability) is scored independently.
- Score: sum of criteria scores / `max_score`, normalized to 0.0-1.0.

---

### Format Summary Table

| Format | Auto-Gradable | Uses `options` | Uses `code_snippet` | Uses `correct_answer` | Uses `grading_rubric` | Response Field |
|---|---|---|---|---|---|---|
| `mcq` | Yes | Yes (A/B/C/D) | No | Yes | No | `selected_option` |
| `code_review` | No | No | Yes | No | Yes | `response_text` |
| `debugging` | No | No | Yes | No | Yes | `response_text` |
| `short_answer` | No | No | No | No | Yes | `response_text` |
| `design_prompt` | No | No | No | No | Yes | `response_text` |

### Pydantic Validation Schemas

```python
class MCQQuestionData(BaseModel):
    """Validation schema for MCQ question fields."""
    options: dict[str, str]  # Must have exactly keys A, B, C, D
    correct_answer: Literal["A", "B", "C", "D"]

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: dict) -> dict:
        if set(v.keys()) != {"A", "B", "C", "D"}:
            raise ValueError("MCQ must have exactly options A, B, C, D")
        return v


class RubricCriterion(BaseModel):
    """Single criterion in a grading rubric."""
    name: str
    description: str
    max_points: int = Field(ge=1)
    key_indicators: list[str] = Field(min_length=1)


class GradingRubric(BaseModel):
    """Grading rubric for non-MCQ formats."""
    criteria: list[RubricCriterion] = Field(min_length=1)
    max_score: int = Field(ge=1)
    passing_threshold: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_score_consistency(self) -> "GradingRubric":
        total_points = sum(c.max_points for c in self.criteria)
        if total_points != self.max_score:
            raise ValueError(
                f"Sum of criteria max_points ({total_points}) "
                f"must equal max_score ({self.max_score})"
            )
        return self


class CodeBasedQuestionData(BaseModel):
    """Validation schema for code_review and debugging question fields."""
    code_snippet: str = Field(min_length=10)
    language: str = Field(min_length=1)
    grading_rubric: GradingRubric
```

### Database Mapping

All formats share the same `questions` table. Format-specific fields are nullable and only populated when relevant:

| Column | MCQ | Code Review | Debugging | Short Answer | Design Prompt |
|---|---|---|---|---|---|
| `title` | Required | Required | Required | Required | Required |
| `body` | Required | Required | Required | Required | Required |
| `code_snippet` | NULL | Required | Required | NULL | NULL |
| `language` | NULL | Required | Required | NULL | NULL |
| `options` | Required (JSONB) | NULL | NULL | NULL | NULL |
| `correct_answer` | Required | NULL | NULL | NULL | NULL |
| `grading_rubric` | NULL | Required (JSONB) | Required (JSONB) | Required (JSONB) | Required (JSONB) |
| `explanation` | Required | Required | Required | Required | Required |
| `metadata` | Optional (JSONB) | Optional (JSONB) | Optional (JSONB) | Optional (JSONB) | Optional (JSONB) |

## Implementation Notes
- All formats share a single `questions` table to simplify queries and avoid table-per-type complexity. Format-specific validation is handled at the application layer, not the database layer.
- The `grading_rubric` JSONB structure is deliberately flexible: different formats may have different numbers of criteria and point distributions. The only constraint is that criteria point totals must equal `max_score`.
- Code snippets in `code_review` and `debugging` formats should be realistic but self-contained (no external dependencies). Snippets should be 20-80 lines to be reviewable within the time budget.
- The `metadata.estimated_time_minutes` field varies significantly by format: MCQ (~1 min), short_answer (~5 min), code_review (~5 min), debugging (~7 min), design_prompt (~10 min). These are advisory and help the frontend display progress estimates.
- The `explanation` field is never shown to the user during the assessment. It is used by the AI grader as reference material and displayed in results after grading is complete.
- MCQ distractors must be plausible: avoiding obviously wrong answers ensures the format tests real understanding, not elimination ability.

## Testing Strategy
- **Unit tests**: Pydantic schema validation for each format (valid data passes, invalid data rejected). MCQ validator rejects options with fewer or more than 4 keys. Rubric validator rejects mismatched `max_score` and criteria point totals.
- **Integration tests**: Store and retrieve questions of each format, verifying nullable fields are correctly handled. Verify format-specific queries (e.g., "all MCQ questions for competency X at difficulty L3").
- **Contract tests**: Validate sample Claude-generated output against the format schemas for all 5 formats.
- **Rendering tests**: Frontend component tests verifying each format renders correctly with sample data (markdown body, syntax-highlighted code, option buttons for MCQ).

## Acceptance Criteria
- [ ] All 5 formats have a defined JSON schema for question structure.
- [ ] All 5 formats have a defined response schema.
- [ ] MCQ questions have exactly 4 options (A/B/C/D) with one correct answer.
- [ ] Non-MCQ formats include a grading rubric with criteria, max_points, and key_indicators.
- [ ] Rubric `max_score` equals the sum of all criteria `max_points`.
- [ ] Code-based formats (`code_review`, `debugging`) require `code_snippet` and `language`.
- [ ] Free-text formats (`short_answer`, `design_prompt`) use `response_text` for user responses.
- [ ] Pydantic validators correctly accept valid data and reject malformed data for each format.
- [ ] Question bodies render correctly as markdown in the frontend.
- [ ] Code snippets display with syntax highlighting for the specified language.
- [ ] The `explanation` and `correct_answer` fields are never exposed to the client during an assessment.
