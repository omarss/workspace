# SPEC-011: Competency and Role Definitions

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-002 (Database schema and migrations)

## Overview
SWET assesses software engineers across 12 competency groups, divided into 8 transferable competencies (applicable to all roles) and 4 context-specific competencies. Each of the 10 supported roles has a unique weight distribution across these competencies, expressed as `question_count` values that sum to exactly 100 per role. These definitions are seeded into the database via a CLI command and serve as the foundation for question generation and assessment assembly.

## Requirements

### Functional
1. The system defines exactly 12 competency groups, each with a unique `slug`, human-readable `name`, `description`, and `category` (either `transferable` or `context`).
2. Each of the 10 roles has a `RoleCompetencyWeight` entry for all 12 competencies, defining both a normalized `weight` (0.0-1.0) and an integer `question_count`.
3. For every role, the sum of `question_count` across all 12 competencies must equal exactly 100.
4. Competency and role weight data is loaded via a CLI seed command (`make seed`).
5. The seed command is idempotent: re-running it does not create duplicates.
6. Competency IDs are stable integers (1-12) to enable foreign key references throughout the system.

### Non-Functional
1. Seed operation completes in under 2 seconds.
2. Competency slugs are URL-safe (lowercase, underscores only).
3. The weight distribution should be meaningful: roles emphasize competencies relevant to their domain (e.g., security role has highest weight for the `security` competency).

## Technical Design

### Competency Groups

#### Transferable Competencies (applicable to all roles)
| ID | Slug | Name | Description |
|---|---|---|---|
| 1 | `problem_solving` | Problem Solving | Breaking down complex problems, identifying root causes, designing effective solutions |
| 2 | `code_quality` | Code Quality | Writing clean, maintainable, readable code following established patterns |
| 3 | `system_design` | System Design | Designing scalable, resilient architectures and making sound trade-offs |
| 4 | `testing` | Testing & QA | Writing effective tests, understanding test strategies, ensuring reliability |
| 5 | `debugging` | Debugging | Systematic identification, isolation, and fixing of software defects |
| 6 | `security` | Security | Security principles, common vulnerabilities, secure coding practices |
| 7 | `performance` | Performance | Optimizing code and systems for speed, efficiency, and resource utilization |
| 8 | `api_design` | API Design | Designing clear, consistent, well-documented APIs and interfaces |

#### Context-Specific Competencies (weighted by role)
| ID | Slug | Name | Description |
|---|---|---|---|
| 9 | `data_modeling` | Data Modeling | Database schemas, data structures, and data flow patterns |
| 10 | `devops` | DevOps & Infrastructure | CI/CD, containerization, cloud infrastructure, deployment |
| 11 | `concurrency` | Concurrency & Async | Concurrent operations, async patterns, parallel processing |
| 12 | `architecture_patterns` | Architecture Patterns | Design patterns, architectural styles, and application |

### Role Competency Weights

Each tuple is `(competency_id, weight, question_count)`. Weights sum to 1.0 and question counts sum to 100 per role.

| Role | Top 3 Competencies (by question_count) |
|---|---|
| `backend` | problem_solving (12), system_design (12), code_quality (10) |
| `frontend` | code_quality (12), problem_solving (10), testing (10) |
| `fullstack` | problem_solving (10), code_quality (10), system_design (10) |
| `mobile` | code_quality (12), performance (12), problem_solving (10) |
| `devops` | devops (14), system_design (12), security (12) |
| `data` | data_modeling (14), problem_solving (12), performance (12) |
| `ml` | problem_solving (14), performance (12), data_modeling (12) |
| `security` | security (18), problem_solving (10), system_design (10) |
| `qa` | testing (18), debugging (14), problem_solving (10) |
| `gamedev` | performance (14), concurrency (12), problem_solving (10) |

### Database Tables

#### `competencies`
- `id` (SMALLINT, PK) - Stable integer 1-12
- `slug` (VARCHAR(50), unique)
- `name` (VARCHAR(100))
- `description` (TEXT)
- `category` (VARCHAR(50)) - `transferable` or `context`

#### `role_competency_weights`
- `id` (UUID, PK)
- `role` (VARCHAR(100), indexed)
- `competency_id` (SMALLINT, FK -> competencies.id)
- `weight` (FLOAT) - Normalized weight 0.0-1.0
- `question_count` (SMALLINT) - Number of questions in a 100-question assessment
- Unique constraint on `(role, competency_id)`

### CLI Seed Command
```bash
make seed  # runs: python -m src.cli.seed
```

The seed script:
1. Iterates over the 12 competency definitions and inserts any that do not already exist (checked by `id`).
2. Iterates over all 10 roles and their 12 weight entries, inserting any that do not already exist (checked by `role` + `competency_id`).
3. Commits the transaction.

## Implementation Notes
- Competency IDs are hardcoded integers (not auto-generated UUIDs) because they are referenced throughout the system as foreign keys and in question generation prompts. Stable IDs prevent drift.
- The weight/question_count split exists because `weight` is used for scoring normalization while `question_count` drives the assessment assembly algorithm (SPEC-014).
- Adding a new competency or role in the future requires updating `COMPETENCIES` and `ROLE_WEIGHTS` in `src/cli/seed.py` and running the seed command. Existing assessments are not affected.
- Context-specific competencies have lower weights for roles where they are less relevant (e.g., `devops` gets 4 questions for a frontend role) but are never zero, ensuring breadth of assessment.

## Testing Strategy
- **Unit tests**: Validate that all 10 roles in `ROLE_WEIGHTS` have exactly 12 entries each, that `question_count` sums to 100 per role, and that `weight` sums to approximately 1.0 per role.
- **Integration tests**: Run seed against a test database, verify 12 competencies and 120 role_competency_weights are created. Re-run seed and verify no duplicates. Verify foreign key references work.
- **Data validation tests**: Programmatic check that every competency_id referenced in `ROLE_WEIGHTS` exists in `COMPETENCIES`.

## Acceptance Criteria
- [ ] 12 competencies are defined with correct slugs, names, descriptions, and categories.
- [ ] 8 competencies have category `transferable`, 4 have category `context`.
- [ ] 10 roles are defined, each with weights for all 12 competencies.
- [ ] `question_count` sums to exactly 100 for every role.
- [ ] `weight` sums to 1.0 (within floating-point tolerance) for every role.
- [ ] `make seed` inserts all data without errors on a fresh database.
- [ ] `make seed` is idempotent: running twice produces no duplicates and no errors.
- [ ] Competency IDs are stable integers 1-12 (not auto-generated).
- [ ] `role_competency_weights` has a unique constraint on `(role, competency_id)`.
