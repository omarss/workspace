"""Tests for the assessment engine (SPEC-014)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.assessments.service import (
    compute_difficulty_allocation,
    interleave_questions,
)
from src.cli.seed import seed_competencies, seed_role_weights
from src.questions.models import Question, QuestionPool

# ---------------------------------------------------------------------------
# Difficulty distribution tests
# ---------------------------------------------------------------------------


class TestComputeDifficultyAllocation:
    def test_allocates_12_questions(self) -> None:
        alloc = compute_difficulty_allocation(12)
        assert sum(alloc.values()) == 12
        # Bell curve shape: L3 should have the most
        assert alloc[3] >= alloc[1]
        assert alloc[3] >= alloc[5]

    def test_allocates_4_questions(self) -> None:
        """Small counts should still distribute correctly."""
        alloc = compute_difficulty_allocation(4)
        assert sum(alloc.values()) == 4

    def test_allocates_100_questions(self) -> None:
        alloc = compute_difficulty_allocation(100)
        assert sum(alloc.values()) == 100
        # Exact values for 100: L1=10, L2=20, L3=35, L4=25, L5=10
        assert alloc[1] == 10
        assert alloc[2] == 20
        assert alloc[3] == 35
        assert alloc[4] == 25
        assert alloc[5] == 10

    def test_allocates_1_question(self) -> None:
        alloc = compute_difficulty_allocation(1)
        assert sum(alloc.values()) == 1

    def test_all_counts_sum_correctly(self) -> None:
        """Verify for various totals that allocations always sum correctly."""
        for total in range(1, 30):
            alloc = compute_difficulty_allocation(total)
            assert sum(alloc.values()) == total, f"Failed for total={total}"


# ---------------------------------------------------------------------------
# Interleaving tests
# ---------------------------------------------------------------------------


class TestInterleaveQuestions:
    def _make_question(self, comp_id: int, fmt: str = "mcq") -> Question:
        """Create a mock Question object."""
        q = Question(
            id=uuid.uuid4(),
            pool_id=uuid.uuid4(),
            competency_id=comp_id,
            format=fmt,
            difficulty=3,
            title=f"Q for comp {comp_id}",
            body="Body text for question",
            explanation="Explanation",
        )
        return q

    def test_interleaves_across_competencies(self) -> None:
        """Questions from different competencies should be mixed."""
        questions_by_comp = {
            1: [self._make_question(1) for _ in range(4)],
            2: [self._make_question(2) for _ in range(4)],
            3: [self._make_question(3) for _ in range(4)],
        }
        result = interleave_questions(questions_by_comp)
        assert len(result) == 12

        # Check that consecutive questions aren't all from the same competency
        consecutive_same = 0
        max_consecutive = 0
        for i in range(1, len(result)):
            if result[i].competency_id == result[i - 1].competency_id:
                consecutive_same += 1
                max_consecutive = max(max_consecutive, consecutive_same)
            else:
                consecutive_same = 0

        # With round-robin, max consecutive should be low
        assert max_consecutive <= 2

    def test_handles_uneven_groups(self) -> None:
        """Groups with different sizes should still interleave correctly."""
        questions_by_comp = {
            1: [self._make_question(1) for _ in range(10)],
            2: [self._make_question(2) for _ in range(3)],
        }
        result = interleave_questions(questions_by_comp)
        assert len(result) == 13

    def test_single_competency(self) -> None:
        """A single competency should return all its questions."""
        questions_by_comp = {
            1: [self._make_question(1) for _ in range(5)],
        }
        result = interleave_questions(questions_by_comp)
        assert len(result) == 5

    def test_empty_input(self) -> None:
        result = interleave_questions({})
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Integration: pool + question fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def seeded_assessment_db(db_session: AsyncSession) -> AsyncSession:
    """Seed competencies, role weights, and create question pools with questions."""
    await seed_competencies(db_session)
    await seed_role_weights(db_session)
    await db_session.flush()

    # Create pools and questions for each competency at each difficulty
    for comp_id in range(1, 13):
        for difficulty in range(1, 6):
            for fmt in ["mcq", "code_review", "debugging", "short_answer", "design_prompt"]:
                pool = QuestionPool(
                    config_hash="test_config_hash_for_backend",
                    competency_id=comp_id,
                    difficulty=difficulty,
                    format=fmt,
                    total_questions=20,
                    generation_status="complete",
                )
                db_session.add(pool)
                await db_session.flush()

                # Add 20 questions per pool
                for i in range(20):
                    if fmt == "mcq":
                        q = Question(
                            pool_id=pool.id,
                            competency_id=comp_id,
                            format=fmt,
                            difficulty=difficulty,
                            title=f"Q{i} comp{comp_id} d{difficulty} {fmt}",
                            body=f"Body for question {i}",
                            options={"A": "a", "B": "b", "C": "c", "D": "d"},
                            correct_answer="A",
                            explanation="Explanation text",
                        )
                    else:
                        q = Question(
                            pool_id=pool.id,
                            competency_id=comp_id,
                            format=fmt,
                            difficulty=difficulty,
                            title=f"Q{i} comp{comp_id} d{difficulty} {fmt}",
                            body=f"Body for question {i}",
                            grading_rubric={
                                "criteria": [
                                    {
                                        "name": "A",
                                        "description": "d",
                                        "max_points": 10,
                                        "key_indicators": ["x"],
                                    }
                                ],
                                "max_score": 10,
                                "passing_threshold": 5,
                            },
                            explanation="Explanation text",
                        )
                        if fmt in ("code_review", "debugging"):
                            q.code_snippet = "def example():\n    pass"
                            q.language = "python"
                    db_session.add(q)

    await db_session.flush()
    return db_session
