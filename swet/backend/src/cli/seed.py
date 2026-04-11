"""Seed the database with initial competency and role weight data."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory
from src.questions.models import Competency, RoleCompetencyWeight

# The 12 engineering competency groups
COMPETENCIES = [
    {
        "id": 1,
        "slug": "problem_solving",
        "name": "Problem Solving",
        "description": "Ability to break down complex problems, identify root causes, and design effective solutions",
        "category": "transferable",
    },
    {
        "id": 2,
        "slug": "code_quality",
        "name": "Code Quality",
        "description": "Writing clean, maintainable, readable code following established patterns and conventions",
        "category": "transferable",
    },
    {
        "id": 3,
        "slug": "system_design",
        "name": "System Design",
        "description": "Designing scalable, resilient architectures and making sound technical trade-offs",
        "category": "transferable",
    },
    {
        "id": 4,
        "slug": "testing",
        "name": "Testing & QA",
        "description": "Writing effective tests, understanding test strategies, and ensuring software reliability",
        "category": "transferable",
    },
    {
        "id": 5,
        "slug": "debugging",
        "name": "Debugging",
        "description": "Systematic approach to identifying, isolating, and fixing defects in software",
        "category": "transferable",
    },
    {
        "id": 6,
        "slug": "security",
        "name": "Security",
        "description": "Understanding security principles, common vulnerabilities, and secure coding practices",
        "category": "transferable",
    },
    {
        "id": 7,
        "slug": "performance",
        "name": "Performance",
        "description": "Optimizing code and systems for speed, efficiency, and resource utilization",
        "category": "transferable",
    },
    {
        "id": 8,
        "slug": "api_design",
        "name": "API Design",
        "description": "Designing clear, consistent, and well-documented APIs and interfaces",
        "category": "transferable",
    },
    {
        "id": 9,
        "slug": "data_modeling",
        "name": "Data Modeling",
        "description": "Designing effective database schemas, data structures, and data flow patterns",
        "category": "context",
    },
    {
        "id": 10,
        "slug": "devops",
        "name": "DevOps & Infrastructure",
        "description": "CI/CD, containerization, cloud infrastructure, and deployment practices",
        "category": "context",
    },
    {
        "id": 11,
        "slug": "concurrency",
        "name": "Concurrency & Async",
        "description": "Managing concurrent operations, async patterns, and parallel processing",
        "category": "context",
    },
    {
        "id": 12,
        "slug": "architecture_patterns",
        "name": "Architecture Patterns",
        "description": "Knowledge of design patterns, architectural styles, and when to apply them",
        "category": "context",
    },
]

# Role-specific competency weights (question_count must sum to 100 per role)
# weight = relative importance (0.0-1.0), question_count = number of questions in assessment
ROLE_WEIGHTS = {
    "backend": [
        (1, 0.12, 12),
        (2, 0.10, 10),
        (3, 0.12, 12),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.10, 10),
        (7, 0.10, 10),
        (8, 0.10, 10),
        (9, 0.08, 8),
        (10, 0.04, 4),
        (11, 0.04, 4),
        (12, 0.04, 4),
    ],
    "frontend": [
        (1, 0.10, 10),
        (2, 0.12, 12),
        (3, 0.08, 8),
        (4, 0.10, 10),
        (5, 0.10, 10),
        (6, 0.08, 8),
        (7, 0.10, 10),
        (8, 0.08, 8),
        (9, 0.04, 4),
        (10, 0.04, 4),
        (11, 0.08, 8),
        (12, 0.08, 8),
    ],
    "fullstack": [
        (1, 0.10, 10),
        (2, 0.10, 10),
        (3, 0.10, 10),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.08, 8),
        (7, 0.08, 8),
        (8, 0.10, 10),
        (9, 0.08, 8),
        (10, 0.06, 6),
        (11, 0.06, 6),
        (12, 0.08, 8),
    ],
    "devops": [
        (1, 0.08, 8),
        (2, 0.06, 6),
        (3, 0.12, 12),
        (4, 0.08, 8),
        (5, 0.10, 10),
        (6, 0.12, 12),
        (7, 0.10, 10),
        (8, 0.06, 6),
        (9, 0.04, 4),
        (10, 0.14, 14),
        (11, 0.04, 4),
        (12, 0.06, 6),
    ],
    "data": [
        (1, 0.12, 12),
        (2, 0.08, 8),
        (3, 0.08, 8),
        (4, 0.08, 8),
        (5, 0.06, 6),
        (6, 0.06, 6),
        (7, 0.12, 12),
        (8, 0.06, 6),
        (9, 0.14, 14),
        (10, 0.06, 6),
        (11, 0.06, 6),
        (12, 0.08, 8),
    ],
    "mobile": [
        (1, 0.10, 10),
        (2, 0.12, 12),
        (3, 0.08, 8),
        (4, 0.10, 10),
        (5, 0.10, 10),
        (6, 0.08, 8),
        (7, 0.12, 12),
        (8, 0.08, 8),
        (9, 0.04, 4),
        (10, 0.04, 4),
        (11, 0.08, 8),
        (12, 0.06, 6),
    ],
    "ml": [
        (1, 0.14, 14),
        (2, 0.06, 6),
        (3, 0.08, 8),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.04, 4),
        (7, 0.12, 12),
        (8, 0.06, 6),
        (9, 0.12, 12),
        (10, 0.06, 6),
        (11, 0.08, 8),
        (12, 0.08, 8),
    ],
    "security": [
        (1, 0.10, 10),
        (2, 0.08, 8),
        (3, 0.10, 10),
        (4, 0.08, 8),
        (5, 0.10, 10),
        (6, 0.18, 18),
        (7, 0.06, 6),
        (8, 0.06, 6),
        (9, 0.04, 4),
        (10, 0.08, 8),
        (11, 0.06, 6),
        (12, 0.06, 6),
    ],
    "qa": [
        (1, 0.10, 10),
        (2, 0.10, 10),
        (3, 0.06, 6),
        (4, 0.18, 18),
        (5, 0.14, 14),
        (6, 0.08, 8),
        (7, 0.08, 8),
        (8, 0.08, 8),
        (9, 0.04, 4),
        (10, 0.06, 6),
        (11, 0.04, 4),
        (12, 0.04, 4),
    ],
    "gamedev": [
        (1, 0.10, 10),
        (2, 0.10, 10),
        (3, 0.08, 8),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.04, 4),
        (7, 0.14, 14),
        (8, 0.06, 6),
        (9, 0.06, 6),
        (10, 0.04, 4),
        (11, 0.12, 12),
        (12, 0.10, 10),
    ],
}


async def seed_competencies(db: AsyncSession) -> None:
    """Seed the 12 competency definitions."""
    for comp_data in COMPETENCIES:
        existing = await db.execute(select(Competency).where(Competency.id == comp_data["id"]))
        if existing.scalar_one_or_none() is None:
            db.add(Competency(**comp_data))
    await db.flush()
    print(f"Seeded {len(COMPETENCIES)} competencies.")


async def seed_role_weights(db: AsyncSession) -> None:
    """Seed role-specific competency weights."""
    count = 0
    for role, weights in ROLE_WEIGHTS.items():
        for competency_id, weight, question_count in weights:
            existing = await db.execute(
                select(RoleCompetencyWeight).where(
                    RoleCompetencyWeight.role == role,
                    RoleCompetencyWeight.competency_id == competency_id,
                )
            )
            if existing.scalar_one_or_none() is None:
                db.add(
                    RoleCompetencyWeight(
                        role=role,
                        competency_id=competency_id,
                        weight=weight,
                        question_count=question_count,
                    )
                )
                count += 1
    await db.flush()
    print(f"Seeded {count} role competency weights.")


async def run_seed() -> None:
    """Run all seed operations."""
    async with async_session_factory() as db:
        await seed_competencies(db)
        await seed_role_weights(db)
        await db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(run_seed())
