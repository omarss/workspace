"""Question pool caching layer (SPEC-013).

Manages question pool lifecycle: creation, generation triggering,
advisory locking for concurrent access, and readiness checking.
"""

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.questions.generator import generate_questions
from src.questions.models import Competency, Question, QuestionPool, RoleCompetencyWeight
from src.questions.schemas import VALID_FORMATS
from src.scoring.circuit_breaker import generation_breaker

logger = logging.getLogger(__name__)

# Failed pools can be retried after this cooldown
FAILED_RETRY_COOLDOWN = timedelta(hours=1)

# Difficulty levels to generate pools for
DIFFICULTY_LEVELS = [1, 2, 3, 4, 5]


def compute_lock_key(
    config_hash: str,
    competency_id: int,
    difficulty: int,
    question_format: str,
) -> int:
    """Compute a 64-bit signed integer lock key from pool identifiers.

    Used for PostgreSQL advisory locks to prevent duplicate generation.
    """
    key_str = f"{config_hash}:{competency_id}:{difficulty}:{question_format}"
    hash_bytes = hashlib.sha256(key_str.encode()).digest()[:8]
    return int.from_bytes(hash_bytes, byteorder="big", signed=True)


async def get_pool(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    difficulty: int,
    question_format: str,
) -> QuestionPool | None:
    """Lookup a specific question pool."""
    result = await db.execute(
        select(QuestionPool).where(
            QuestionPool.config_hash == config_hash,
            QuestionPool.competency_id == competency_id,
            QuestionPool.difficulty == difficulty,
            QuestionPool.format == question_format,
        )
    )
    return result.scalar_one_or_none()


async def get_or_create_pool(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    difficulty: int,
    question_format: str,
) -> QuestionPool:
    """Get an existing pool or create a new one in pending status.

    If the pool exists and is failed (past cooldown), resets it to pending.
    """
    pool = await get_pool(db, config_hash, competency_id, difficulty, question_format)

    if pool is not None:
        # Reset failed pools past the cooldown period
        if pool.generation_status == "failed":
            cooldown_cutoff = datetime.now(UTC) - FAILED_RETRY_COOLDOWN
            if pool.updated_at.replace(tzinfo=UTC) < cooldown_cutoff:
                pool.generation_status = "pending"
                await db.flush()
        return pool

    # Create new pool
    pool = QuestionPool(
        config_hash=config_hash,
        competency_id=competency_id,
        difficulty=difficulty,
        format=question_format,
        generation_status="pending",
    )
    db.add(pool)
    await db.flush()
    return pool


async def trigger_generation(
    db: AsyncSession,
    pool: QuestionPool,
    competency_name: str,
    competency_description: str,
    role: str,
    languages: list[str],
    frameworks: list[str],
) -> None:
    """Generate questions for a pool and update its status.

    Sets pool to 'generating', calls the LLM, stores results,
    and updates status to 'complete' or 'failed'.
    """
    # Mark as generating
    pool.generation_status = "generating"
    await db.flush()

    try:
        questions = await generation_breaker.execute(
            generate_questions(
                competency_name=competency_name,
                competency_description=competency_description,
                difficulty=pool.difficulty,
                question_format=pool.format,
                role=role,
                languages=languages,
                frameworks=frameworks,
            )
        )

        # Store generated questions
        for q in questions:
            question = Question(
                pool_id=pool.id,
                competency_id=pool.competency_id,
                format=pool.format,
                difficulty=pool.difficulty,
                title=q.title,
                body=q.body,
                code_snippet=q.code_snippet,
                language=q.language,
                options=q.options,
                correct_answer=q.correct_answer,
                grading_rubric=(q.grading_rubric.model_dump() if q.grading_rubric else None),
                explanation=q.explanation,
                question_metadata=(q.metadata.model_dump() if q.metadata else None),
            )
            db.add(question)

        pool.total_questions = len(questions)
        pool.generation_status = "complete"
        await db.flush()

        logger.info(
            "Pool %s: generated %d questions (competency=%d, difficulty=%d, format=%s)",
            pool.id,
            len(questions),
            pool.competency_id,
            pool.difficulty,
            pool.format,
        )

    except Exception:
        logger.exception("Pool %s: generation failed", pool.id)
        pool.generation_status = "failed"
        await db.flush()


async def get_required_pools_status(
    db: AsyncSession,
    config_hash: str,
    role: str,
) -> dict[str, int]:
    """Check the status of all required pools for a config.

    Returns a dict with counts per status: {pending: N, generating: N, complete: N, failed: N}.
    """
    # Get the role's competency weights to know which competencies are needed
    weights_result = await db.execute(
        select(RoleCompetencyWeight).where(RoleCompetencyWeight.role == role)
    )
    weights = weights_result.scalars().all()

    if not weights:
        return {"pending": 0, "generating": 0, "complete": 0, "failed": 0}

    # Count existing pools and their statuses
    pools_result = await db.execute(
        select(QuestionPool).where(QuestionPool.config_hash == config_hash)
    )
    pools = pools_result.scalars().all()

    pool_map: dict[tuple[int, int, str], str] = {}
    for p in pools:
        pool_map[(p.competency_id, p.difficulty, p.format)] = p.generation_status

    # Count statuses for all required pool combinations
    status_counts: dict[str, int] = {"pending": 0, "generating": 0, "complete": 0, "failed": 0}

    for weight in weights:
        if weight.question_count == 0:
            continue
        for difficulty in DIFFICULTY_LEVELS:
            for fmt in VALID_FORMATS:
                status = pool_map.get((weight.competency_id, difficulty, fmt), "missing")
                if status == "missing":
                    status_counts["pending"] += 1
                else:
                    status_counts[status] = status_counts.get(status, 0) + 1

    return status_counts


async def create_pending_pools(
    db: AsyncSession,
    config_hash: str,
    role: str,
) -> int:
    """Create all required pools in pending status. Returns the number created."""
    weights_result = await db.execute(
        select(RoleCompetencyWeight).where(RoleCompetencyWeight.role == role)
    )
    weights = weights_result.scalars().all()
    created = 0

    for weight in weights:
        if weight.question_count == 0:
            continue
        for difficulty in DIFFICULTY_LEVELS:
            for fmt in VALID_FORMATS:
                await get_or_create_pool(db, config_hash, weight.competency_id, difficulty, fmt)
                created += 1

    return created


async def generate_next_pending_pool(
    db: AsyncSession,
    config_hash: str,
    role: str,
    languages: list[str],
    frameworks: list[str],
) -> bool:
    """Generate the next pending pool. Returns True if a pool was generated, False if none left.

    Uses SELECT ... FOR UPDATE SKIP LOCKED to allow safe concurrent generation.
    """
    # Find and lock the next pending pool (skip already-locked rows)
    pool_result = await db.execute(
        select(QuestionPool)
        .where(
            QuestionPool.config_hash == config_hash,
            QuestionPool.generation_status == "pending",
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    pool = pool_result.scalar_one_or_none()

    if pool is None:
        return False

    # Load competency info for the prompt
    comp_result = await db.execute(select(Competency).where(Competency.id == pool.competency_id))
    comp = comp_result.scalar_one_or_none()
    if not comp:
        pool.generation_status = "failed"
        await db.flush()
        return True

    await trigger_generation(
        db=db,
        pool=pool,
        competency_name=comp.name,
        competency_description=comp.description,
        role=role,
        languages=languages,
        frameworks=frameworks,
    )

    return True


async def ensure_pools_ready(
    db: AsyncSession,
    config_hash: str,
    role: str,
    languages: list[str],
    frameworks: list[str],
) -> bool:
    """Ensure all required pools exist and trigger generation for missing/failed ones.

    Returns True if all pools are complete, False if some are still pending/generating.
    """
    # Get role weights and competency info
    weights_result = await db.execute(
        select(RoleCompetencyWeight).where(RoleCompetencyWeight.role == role)
    )
    weights = weights_result.scalars().all()

    if not weights:
        return False

    # Get competency details for prompt context
    comp_ids = [w.competency_id for w in weights]
    comps_result = await db.execute(select(Competency).where(Competency.id.in_(comp_ids)))
    competencies = {c.id: c for c in comps_result.scalars().all()}

    all_ready = True
    for weight in weights:
        if weight.question_count == 0:
            continue

        comp = competencies.get(weight.competency_id)
        if not comp:
            continue

        for difficulty in DIFFICULTY_LEVELS:
            for fmt in VALID_FORMATS:
                pool = await get_or_create_pool(
                    db, config_hash, weight.competency_id, difficulty, fmt
                )

                if pool.generation_status == "complete":
                    continue

                if pool.generation_status == "pending":
                    # Trigger generation
                    await trigger_generation(
                        db=db,
                        pool=pool,
                        competency_name=comp.name,
                        competency_description=comp.description,
                        role=role,
                        languages=languages,
                        frameworks=frameworks,
                    )

                    if pool.generation_status != "complete":
                        all_ready = False
                else:
                    # Still generating or failed
                    all_ready = False

    return all_ready


async def get_available_questions(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    difficulty: int,
    question_format: str,
) -> list[Question]:
    """Get all available questions from a completed pool."""
    # First find the pool
    pool = await get_pool(db, config_hash, competency_id, difficulty, question_format)
    if pool is None or pool.generation_status != "complete":
        return []

    result = await db.execute(select(Question).where(Question.pool_id == pool.id))
    return list(result.scalars().all())


async def update_pool_status(
    db: AsyncSession,
    pool_id: str,
    status: str,
    total_questions: int | None = None,
) -> None:
    """Update the status of a question pool."""
    values: dict[str, object] = {"generation_status": status}
    if total_questions is not None:
        values["total_questions"] = total_questions

    await db.execute(update(QuestionPool).where(QuestionPool.id == pool_id).values(**values))
    await db.flush()
