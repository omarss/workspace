# SPEC-002: Database Schema and Migrations

## Status
Approved

## Priority
P0

## Dependencies
- SPEC-001

## Overview
Define the complete database schema for the SWET platform covering all 13 tables across 5 domains (auth, onboarding, questions, assessments, scoring). This spec also covers the Alembic async migration setup, seed data for the 12 core competencies, and 10 role-based competency weight sets. The schema is designed to support the full assessment lifecycle from user registration through grading and results.

## Requirements

### Functional
1. 13 database tables organized across 5 domain modules
2. Alembic migration setup with async SQLAlchemy support (asyncpg driver)
3. Primary keys and timestamps follow model contracts: most tables use UUID primary keys with `created_at`/`updated_at`, while lookup/history tables may use stable non-UUID keys where appropriate
4. Foreign key constraints with appropriate `ON DELETE` cascade rules
5. Seed data: 12 competency definitions covering core software engineering areas
6. Seed data: 10 role-based competency weight sets (e.g., Frontend, Backend, Full-Stack, DevOps, etc.)
7. CLI command (`make seed` / `python -m src.cli.seed`) to populate seed data idempotently
8. Indexes on frequently queried columns (foreign keys, config_hash, status fields)

### Non-Functional
1. All migrations must be reversible (upgrade + downgrade)
2. Seed command must be idempotent -- safe to run multiple times without duplicating data
3. Schema must support concurrent assessments by multiple users without contention
4. External-facing entities use non-guessable IDs (UUID) in URLs/APIs

## Technical Design

### Database Configuration
- **Engine**: PostgreSQL 18 via Docker Compose
- **Driver**: asyncpg (async SQLAlchemy)
- **Connection**: `postgresql+asyncpg://swet:swet_local@localhost:5432/swet`
- **Session**: async scoped sessions via `async_sessionmaker`

### Table Definitions

#### Auth Domain (`src/auth/models.py`)

**users**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| github_id | BigInteger | UNIQUE, indexed, NOT NULL |
| github_username | String(255) | NOT NULL |
| email | String(255) | nullable |
| avatar_url | String | nullable |
| is_active | Boolean | default True |
| onboarding_completed | Boolean | default False |
| created_at | DateTime | default now, NOT NULL |
| updated_at | DateTime | default now, onupdate now, NOT NULL |

#### Onboarding Domain (`src/onboarding/models.py`)

**user_profiles**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK -> users.id, UNIQUE, NOT NULL |
| primary_role | String(100) | NOT NULL (e.g., "backend", "frontend", "fullstack") |
| interests | JSON | NOT NULL (list of strings) |
| technologies | JSON | NOT NULL (`{languages: [...], frameworks: [...]}`) |
| experience_years | Integer | nullable |
| config_hash | String(64) | indexed, nullable |
| created_at | DateTime | NOT NULL |
| updated_at | DateTime | NOT NULL |

#### Questions Domain (`src/questions/models.py`)

**competencies**
| Column | Type | Constraints |
|--------|------|-------------|
| id | SmallInteger | PK (stable IDs 1-12) |
| name | String | UNIQUE, NOT NULL |
| slug | String | UNIQUE, NOT NULL |
| description | Text | NOT NULL |
| category | String | NOT NULL |

**role_competency_weights**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| role | String | NOT NULL |
| competency_id | SmallInteger | FK -> competencies.id, NOT NULL |
| weight | Float | NOT NULL (0.0 - 1.0) |
| question_count | SmallInteger | NOT NULL |
| | | UNIQUE(role, competency_id) |

**question_pools**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| config_hash | String(64) | indexed, NOT NULL |
| competency_id | SmallInteger | FK -> competencies.id, NOT NULL |
| difficulty | SmallInteger | NOT NULL |
| format | String(30) | NOT NULL (`mcq`, `code_review`, `debugging`, `short_answer`, `design_prompt`) |
| total_questions | Integer | default 0, NOT NULL |
| generation_status | String(20) | default `pending`, NOT NULL |
| created_at | DateTime | NOT NULL |
| updated_at | DateTime | NOT NULL |

**questions**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| pool_id | UUID | FK -> question_pools.id, NOT NULL |
| competency_id | SmallInteger | FK -> competencies.id, NOT NULL |
| format | String(30) | NOT NULL |
| difficulty | SmallInteger | NOT NULL |
| title | String(500) | NOT NULL |
| body | Text | NOT NULL |
| code_snippet | Text | nullable |
| language | String(50) | nullable |
| options | JSON | nullable |
| correct_answer | Text | nullable |
| grading_rubric | JSON | nullable |
| explanation | Text | nullable |
| metadata | JSON | nullable |
| created_at | DateTime | NOT NULL |
| updated_at | DateTime | NOT NULL |

**user_question_history**
| Column | Type | Constraints |
|--------|------|-------------|
| id | BigInteger | PK, autoincrement |
| user_id | UUID | FK -> users.id, NOT NULL |
| question_id | UUID | FK -> questions.id, NOT NULL |
| seen_at | DateTime | NOT NULL |
| | | UNIQUE(user_id, question_id) |

#### Assessments Domain (`src/assessments/models.py`)

**assessments**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK -> users.id, NOT NULL |
| config_hash | String(64) | NOT NULL |
| status | String | NOT NULL ("in_progress", "paused", "completed", "expired") |
| total_questions | Integer | default 100, NOT NULL |
| current_question_index | Integer | default 0, NOT NULL |
| is_timed | Boolean | default False, NOT NULL |
| time_limit_minutes | Integer | nullable |
| started_at | DateTime | NOT NULL |
| completed_at | DateTime | nullable |
| created_at | DateTime | NOT NULL |
| updated_at | DateTime | NOT NULL |

**assessment_questions**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| assessment_id | UUID | FK -> assessments.id, NOT NULL |
| question_id | UUID | FK -> questions.id, NOT NULL |
| position | SmallInteger | NOT NULL |
| competency_id | SmallInteger | FK -> competencies.id, NOT NULL |
| | | UNIQUE(assessment_id, position) |
| | | UNIQUE(assessment_id, question_id) |

**answers**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| assessment_id | UUID | FK -> assessments.id, NOT NULL |
| question_id | UUID | FK -> questions.id, NOT NULL |
| user_id | UUID | FK -> users.id, NOT NULL |
| response_text | Text | nullable |
| selected_option | String(10) | nullable |
| time_spent_seconds | Integer | default 0, NOT NULL |
| is_auto_saved | Boolean | default False, NOT NULL |
| submitted_at | DateTime | nullable |
| created_at | DateTime | NOT NULL |
| updated_at | DateTime | NOT NULL |
| | | UNIQUE(assessment_id, question_id) |

#### Scoring Domain (`src/scoring/models.py`)

**assessment_results**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| assessment_id | UUID | FK -> assessments.id, UNIQUE, NOT NULL |
| user_id | UUID | FK -> users.id, indexed, NOT NULL |
| overall_score | Float | NOT NULL (0.0 - 100.0) |
| overall_proficiency_level | SmallInteger | default 0, NOT NULL |
| proficiency_label | String(50) | default "novice", NOT NULL |
| total_time_seconds | Integer | default 0, NOT NULL |
| grading_status | String(20) | default "pending", NOT NULL |
| created_at | DateTime | NOT NULL |
| updated_at | DateTime | NOT NULL |

**competency_scores**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| result_id | UUID | FK -> assessment_results.id, NOT NULL |
| competency_id | SmallInteger | FK -> competencies.id, NOT NULL |
| score | Float | default 0.0, NOT NULL |
| proficiency_level | SmallInteger | default 0, NOT NULL |
| questions_total | Integer | default 0, NOT NULL |
| questions_correct | Integer | default 0, NOT NULL |
| ai_graded_avg | Float | nullable |

**answer_grades**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| answer_id | UUID | FK -> answers.id, UNIQUE, NOT NULL |
| grading_method | String | NOT NULL ("auto", "ai") |
| is_correct | Boolean | nullable |
| score | Float | default 0.0, NOT NULL |
| feedback | Text | nullable |
| rubric_breakdown | JSON | nullable |
| graded_at | DateTime | NOT NULL |

### Seed Data

#### 12 Competencies
| Slug | Name | Category |
|------|------|----------|
| problem_solving | Problem Solving | transferable |
| code_quality | Code Quality | transferable |
| system_design | System Design | transferable |
| testing | Testing & QA | transferable |
| debugging | Debugging | transferable |
| security | Security | transferable |
| performance | Performance | transferable |
| api_design | API Design | transferable |
| data_modeling | Data Modeling | context |
| devops | DevOps & Infrastructure | context |
| concurrency | Concurrency & Async | context |
| architecture_patterns | Architecture Patterns | context |

#### 10 Role Weight Sets
Roles: `backend`, `frontend`, `fullstack`, `devops`, `data`, `mobile`, `ml`, `security`, `qa`, `gamedev`

Each role maps all 12 competencies to a weight (0.0-1.0) reflecting how critical that competency is for the role. Weights are normalized so they sum to 1.0 per role.

### Alembic Configuration
- `alembic.ini` points to `alembic/` directory
- `alembic/env.py` uses async engine (`run_async_migrations`)
- Target metadata imported from all domain model modules
- Migration naming: `YYYY_MM_DD_HHMM_description.py`

## Implementation Notes
- All models inherit from a shared `Base` declarative base defined in `src/database.py`.
- Use `mapped_column` with `Mapped[]` type annotations (SQLAlchemy 2.0 style) for full mypy compatibility.
- Question payload fields are normalized in first-class columns (`title`, `body`, `options`, `grading_rubric`, etc.) instead of a single `content` JSON blob.
- `config_hash` is a SHA-256 hash of normalized onboarding inputs (`role`, sorted `interests`, sorted `languages`, sorted `frameworks`).
- The `user_question_history` table enables uniqueness enforcement -- a user never sees the same question twice across assessments.
- Seed data insertion should use `INSERT ... ON CONFLICT DO NOTHING` semantics for idempotency.

### Recommended Hardening
- Add DB `CHECK` constraints (or constrained enums) for enum-like columns such as `questions.format`, `assessments.status`, and `assessment_results.grading_status`.
- Add a unique constraint on `competency_scores(result_id, competency_id)` for strict idempotent upserts in results computation flows.
- Add composite indexes for high-volume query paths (`assessment_results(user_id, created_at)`, `answers(assessment_id, question_id)`, and `question_pools(config_hash, competency_id, difficulty, format)`).

## Testing Strategy
- Unit tests for: Model instantiation, relationship loading, default values, seed data content validation
- Integration tests for: Alembic migration up/down cycle, seed command idempotency, foreign key constraint enforcement, unique constraint violations
- E2E tests for: N/A at this stage

## Acceptance Criteria
- [ ] `make migrate` applies all migrations and creates 13 tables in PostgreSQL
- [ ] `make seed` populates 12 competencies and 10 role weight sets (120 weight rows)
- [ ] Running `make seed` twice produces no duplicates or errors
- [ ] All foreign key relationships are correctly enforced (deleting a parent cascades or raises)
- [ ] `alembic downgrade base` cleanly drops all tables
- [ ] `alembic upgrade head` followed by `alembic downgrade -1` followed by `alembic upgrade head` succeeds
- [ ] UUID primary keys are generated automatically for UUID-keyed tables
- [ ] `created_at` and `updated_at` timestamps are populated automatically
- [ ] Unique constraints prevent duplicate `github_id`, `(role, competency_id)`, `(assessment_id, question_id)`, and `(user_id, question_id)`
