"""Tests for question caching layer (SPEC-013)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cli.seed import seed_competencies
from src.questions.cache import (
    compute_lock_key,
    get_available_questions,
    get_or_create_pool,
    get_pool,
    trigger_generation,
)
from src.questions.models import Question, QuestionPool
from src.questions.schemas import GeneratedQuestion, GradingRubric, RubricCriterion

# ---------------------------------------------------------------------------
# Lock key computation
# ---------------------------------------------------------------------------


class TestComputeLockKey:
    def test_deterministic(self) -> None:
        """Same inputs produce the same lock key."""
        key1 = compute_lock_key("abc123", 1, 3, "mcq")
        key2 = compute_lock_key("abc123", 1, 3, "mcq")
        assert key1 == key2

    def test_different_inputs_produce_different_keys(self) -> None:
        key1 = compute_lock_key("abc123", 1, 3, "mcq")
        key2 = compute_lock_key("abc123", 1, 3, "code_review")
        assert key1 != key2

    def test_returns_signed_64bit_integer(self) -> None:
        key = compute_lock_key("test", 1, 1, "mcq")
        assert -(2**63) <= key <= (2**63 - 1)


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------


class TestGetPool:
    async def test_returns_none_for_nonexistent(self, db_session: AsyncSession) -> None:
        pool = await get_pool(db_session, "nonexistent", 1, 1, "mcq")
        assert pool is None

    async def test_returns_existing_pool(self, db_session: AsyncSession) -> None:
        # Create a pool
        pool = QuestionPool(
            config_hash="test_hash",
            competency_id=1,
            difficulty=2,
            format="mcq",
            generation_status="complete",
            total_questions=20,
        )
        db_session.add(pool)

        # Need competency to exist for FK
        await seed_competencies(db_session)
        await db_session.flush()

        found = await get_pool(db_session, "test_hash", 1, 2, "mcq")
        assert found is not None
        assert found.generation_status == "complete"


class TestGetOrCreatePool:
    @pytest.fixture
    async def seeded_db(self, db_session: AsyncSession) -> AsyncSession:
        await seed_competencies(db_session)
        await db_session.flush()
        return db_session

    async def test_creates_new_pool(self, seeded_db: AsyncSession) -> None:
        pool = await get_or_create_pool(seeded_db, "new_hash", 1, 3, "mcq")
        assert pool is not None
        assert pool.generation_status == "pending"
        assert pool.config_hash == "new_hash"
        assert pool.competency_id == 1
        assert pool.difficulty == 3

    async def test_returns_existing_pool(self, seeded_db: AsyncSession) -> None:
        # Create first
        pool1 = await get_or_create_pool(seeded_db, "hash1", 2, 1, "mcq")
        await seeded_db.flush()

        # Get again
        pool2 = await get_or_create_pool(seeded_db, "hash1", 2, 1, "mcq")
        assert pool1.id == pool2.id


# ---------------------------------------------------------------------------
# Generation trigger
# ---------------------------------------------------------------------------


class TestTriggerGeneration:
    @pytest.fixture
    async def seeded_db(self, db_session: AsyncSession) -> AsyncSession:
        await seed_competencies(db_session)
        await db_session.flush()
        return db_session

    def _make_mock_questions(self, fmt: str = "mcq", count: int = 3) -> list[GeneratedQuestion]:
        """Create mock GeneratedQuestion instances."""
        questions = []
        for i in range(count):
            if fmt == "mcq":
                q = GeneratedQuestion(
                    format="mcq",
                    title=f"MCQ question {i} for testing",
                    body=f"Choose the best answer for question {i}...",
                    options={"A": "a", "B": "b", "C": "c", "D": "d"},
                    correct_answer="A",
                    explanation=f"A is correct because it is the right choice for {i}.",
                )
            else:
                q = GeneratedQuestion(
                    format=fmt,
                    title=f"{fmt} question {i} for testing",
                    body=f"Answer this {fmt} question {i}...",
                    grading_rubric=GradingRubric(
                        criteria=[
                            RubricCriterion(
                                name="Analysis",
                                description="Quality",
                                max_points=10,
                                key_indicators=["good"],
                            )
                        ],
                        max_score=10,
                        passing_threshold=5,
                    ),
                    explanation=f"The expected answer covers {fmt} topic {i}.",
                )
            questions.append(q)
        return questions

    @patch("src.questions.cache.generate_questions")
    async def test_successful_generation(
        self, mock_generate: AsyncMock, seeded_db: AsyncSession
    ) -> None:
        mock_generate.return_value = self._make_mock_questions("mcq", 5)

        pool = await get_or_create_pool(seeded_db, "gen_test", 1, 2, "mcq")
        await trigger_generation(
            db=seeded_db,
            pool=pool,
            competency_name="Problem Solving",
            competency_description="Breaking down complex problems",
            role="backend",
            languages=["python"],
            frameworks=["fastapi"],
        )

        assert pool.generation_status == "complete"
        assert pool.total_questions == 5

        # Verify questions were stored
        result = await seeded_db.execute(select(Question).where(Question.pool_id == pool.id))
        stored = result.scalars().all()
        assert len(stored) == 5

    @patch("src.questions.cache.generate_questions")
    async def test_failed_generation(
        self, mock_generate: AsyncMock, seeded_db: AsyncSession
    ) -> None:
        mock_generate.side_effect = ValueError("API error")

        pool = await get_or_create_pool(seeded_db, "fail_test", 1, 2, "mcq")
        await trigger_generation(
            db=seeded_db,
            pool=pool,
            competency_name="Problem Solving",
            competency_description="Breaking down complex problems",
            role="backend",
            languages=["python"],
            frameworks=[],
        )

        assert pool.generation_status == "failed"


# ---------------------------------------------------------------------------
# Available questions retrieval
# ---------------------------------------------------------------------------


class TestGetAvailableQuestions:
    @pytest.fixture
    async def seeded_db(self, db_session: AsyncSession) -> AsyncSession:
        await seed_competencies(db_session)
        await db_session.flush()
        return db_session

    async def test_returns_empty_for_no_pool(self, seeded_db: AsyncSession) -> None:
        result = await get_available_questions(seeded_db, "missing", 1, 1, "mcq")
        assert result == []

    @patch("src.questions.cache.generate_questions")
    async def test_returns_questions_from_complete_pool(
        self, mock_generate: AsyncMock, seeded_db: AsyncSession
    ) -> None:
        # Create mock questions
        mock_generate.return_value = [
            GeneratedQuestion(
                format="mcq",
                title=f"Question {i} about testing",
                body=f"Choose the best answer for {i}...",
                options={"A": "a", "B": "b", "C": "c", "D": "d"},
                correct_answer="A",
                explanation=f"A is correct because it is the right answer for {i}.",
            )
            for i in range(3)
        ]

        pool = await get_or_create_pool(seeded_db, "avail_test", 1, 2, "mcq")
        await trigger_generation(
            db=seeded_db,
            pool=pool,
            competency_name="Problem Solving",
            competency_description="Desc",
            role="backend",
            languages=[],
            frameworks=[],
        )

        questions = await get_available_questions(seeded_db, "avail_test", 1, 2, "mcq")
        assert len(questions) == 3
