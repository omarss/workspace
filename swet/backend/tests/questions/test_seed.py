"""Tests for competency and role weight seed data (SPEC-011)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cli.seed import COMPETENCIES, ROLE_WEIGHTS, seed_competencies, seed_role_weights
from src.questions.models import Competency, RoleCompetencyWeight

# ---------------------------------------------------------------------------
# Data validation tests (no database needed)
# ---------------------------------------------------------------------------


class TestSeedDataValidation:
    """Validate the seed data constants before any DB interaction."""

    def test_exactly_12_competencies(self):
        assert len(COMPETENCIES) == 12

    def test_competency_ids_are_1_to_12(self):
        ids = [c["id"] for c in COMPETENCIES]
        assert sorted(ids) == list(range(1, 13))

    def test_competency_slugs_are_unique(self):
        slugs = [c["slug"] for c in COMPETENCIES]
        assert len(slugs) == len(set(slugs))

    def test_competency_slugs_are_url_safe(self):
        """Slugs should be lowercase with underscores only."""
        import re

        for comp in COMPETENCIES:
            assert re.match(r"^[a-z][a-z0-9_]*$", comp["slug"]), (
                f"Slug '{comp['slug']}' is not URL-safe"
            )

    def test_transferable_and_context_categories(self):
        categories = {c["category"] for c in COMPETENCIES}
        assert categories == {"transferable", "context"}

        transferable = [c for c in COMPETENCIES if c["category"] == "transferable"]
        context = [c for c in COMPETENCIES if c["category"] == "context"]
        assert len(transferable) == 8
        assert len(context) == 4

    def test_exactly_10_roles(self):
        assert len(ROLE_WEIGHTS) == 10

    def test_each_role_has_12_entries(self):
        for role, weights in ROLE_WEIGHTS.items():
            assert len(weights) == 12, f"Role '{role}' has {len(weights)} entries, expected 12"

    def test_question_count_sums_to_100(self):
        for role, weights in ROLE_WEIGHTS.items():
            total = sum(qc for _, _, qc in weights)
            assert total == 100, f"Role '{role}' question_count sums to {total}, expected 100"

    def test_weight_sums_to_approximately_1(self):
        for role, weights in ROLE_WEIGHTS.items():
            total = sum(w for _, w, _ in weights)
            assert abs(total - 1.0) < 0.01, f"Role '{role}' weight sums to {total}, expected ~1.0"

    def test_all_competency_ids_in_weights_exist(self):
        """Every competency_id referenced in weights must exist in COMPETENCIES."""
        valid_ids = {c["id"] for c in COMPETENCIES}
        for role, weights in ROLE_WEIGHTS.items():
            for comp_id, _, _ in weights:
                assert comp_id in valid_ids, (
                    f"Role '{role}' references competency_id {comp_id} which doesn't exist"
                )

    def test_no_duplicate_competency_ids_per_role(self):
        for role, weights in ROLE_WEIGHTS.items():
            comp_ids = [comp_id for comp_id, _, _ in weights]
            assert len(comp_ids) == len(set(comp_ids)), (
                f"Role '{role}' has duplicate competency_id entries"
            )

    def test_question_counts_are_positive(self):
        for role, weights in ROLE_WEIGHTS.items():
            for comp_id, _, qc in weights:
                assert qc > 0, (
                    f"Role '{role}', competency {comp_id} has question_count {qc} (must be > 0)"
                )


# ---------------------------------------------------------------------------
# Integration tests (use test database)
# ---------------------------------------------------------------------------


class TestSeedDatabase:
    """Test seeding against the database."""

    @pytest.fixture
    async def seeded_db(self, db_session: AsyncSession) -> AsyncSession:
        """Seed competencies and role weights into the test DB."""
        await seed_competencies(db_session)
        await seed_role_weights(db_session)
        await db_session.flush()
        return db_session

    async def test_seed_creates_12_competencies(self, seeded_db: AsyncSession):
        result = await seeded_db.execute(select(func.count(Competency.id)))
        count = result.scalar()
        assert count == 12

    async def test_seed_creates_120_role_weights(self, seeded_db: AsyncSession):
        result = await seeded_db.execute(select(func.count(RoleCompetencyWeight.id)))
        count = result.scalar()
        assert count == 120  # 10 roles * 12 competencies

    async def test_seed_is_idempotent(self, seeded_db: AsyncSession):
        """Re-running seed should not create duplicates."""
        # Seed again
        await seed_competencies(seeded_db)
        await seed_role_weights(seeded_db)
        await seeded_db.flush()

        # Counts should remain the same
        comp_count = (await seeded_db.execute(select(func.count(Competency.id)))).scalar()
        weight_count = (
            await seeded_db.execute(select(func.count(RoleCompetencyWeight.id)))
        ).scalar()
        assert comp_count == 12
        assert weight_count == 120

    async def test_competency_data_integrity(self, seeded_db: AsyncSession):
        """Verify a specific competency was seeded correctly."""
        result = await seeded_db.execute(select(Competency).where(Competency.id == 1))
        comp = result.scalar_one()
        assert comp.slug == "problem_solving"
        assert comp.name == "Problem Solving"
        assert comp.category == "transferable"

    async def test_role_weight_data_integrity(self, seeded_db: AsyncSession):
        """Verify role weights for a specific role."""
        result = await seeded_db.execute(
            select(RoleCompetencyWeight).where(RoleCompetencyWeight.role == "backend")
        )
        weights = result.scalars().all()
        assert len(weights) == 12
        total_qc = sum(w.question_count for w in weights)
        assert total_qc == 100
