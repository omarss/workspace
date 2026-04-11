"""Tests for results history, stats, and trend endpoints (SPEC-032/034)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.scoring.models import AssessmentResult
from src.scoring.service import get_history, get_history_stats, get_trend_data


@pytest.fixture
async def history_db(db_session: AsyncSession):
    """Set up multiple assessment results for history testing."""
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    assessment_ids = []

    now = datetime.now(UTC)
    for i in range(5):
        aid = uuid.uuid4()
        assessment_ids.append(aid)
        result = AssessmentResult(
            assessment_id=aid,
            user_id=user_id,
            overall_score=50.0 + i * 10,  # 50, 60, 70, 80, 90
            overall_proficiency_level=3 + (i // 2),
            proficiency_label=["intermediate", "intermediate", "advanced", "advanced", "expert"][i],
            total_time_seconds=1800 + i * 300,
            grading_status="complete",
            created_at=now - timedelta(days=30 - i * 7),  # Older first
        )
        db_session.add(result)

    # Add a result for a different user (should not appear in queries)
    other_result = AssessmentResult(
        assessment_id=uuid.uuid4(),
        user_id=other_user_id,
        overall_score=95.0,
        overall_proficiency_level=5,
        proficiency_label="expert",
        total_time_seconds=2000,
        grading_status="complete",
    )
    db_session.add(other_result)

    # Add a pending result for the user (for status filtering)
    pending_aid = uuid.uuid4()
    pending_result = AssessmentResult(
        assessment_id=pending_aid,
        user_id=user_id,
        overall_score=0.0,
        overall_proficiency_level=1,
        proficiency_label="novice",
        total_time_seconds=0,
        grading_status="grading",
    )
    db_session.add(pending_result)
    await db_session.flush()

    return {
        "db": db_session,
        "user_id": user_id,
        "other_user_id": other_user_id,
        "assessment_ids": assessment_ids,
        "pending_aid": pending_aid,
    }


@pytest.mark.asyncio
async def test_get_history_returns_paginated_results(history_db):
    """History should return paginated results ordered by date desc."""
    db = history_db["db"]
    user_id = history_db["user_id"]

    items, total = await get_history(db, user_id, page=1, per_page=3)
    assert total == 6  # 5 complete + 1 grading
    assert len(items) == 3

    # Most recent first - pending result has latest created_at so it's first
    # Verify ordering is by date descending (later items have earlier dates)
    for i in range(len(items) - 1):
        assert items[i].created_at >= items[i + 1].created_at


@pytest.mark.asyncio
async def test_get_history_page_2(history_db):
    """Second page should return remaining items."""
    db = history_db["db"]
    user_id = history_db["user_id"]

    items, total = await get_history(db, user_id, page=2, per_page=3)
    assert total == 6
    assert len(items) == 3  # 6 total, page 2 of 3 per page = 3 items


@pytest.mark.asyncio
async def test_get_history_filter_by_status(history_db):
    """Filtering by status should narrow results."""
    db = history_db["db"]
    user_id = history_db["user_id"]

    items, total = await get_history(db, user_id, status="complete")
    assert total == 5  # Only complete results

    items, total = await get_history(db, user_id, status="grading")
    assert total == 1  # Only grading result


@pytest.mark.asyncio
async def test_get_history_excludes_other_users(history_db):
    """History should only return results for the specified user."""
    db = history_db["db"]
    other_user_id = history_db["other_user_id"]

    items, total = await get_history(db, other_user_id)
    assert total == 1  # Only the other user's result


@pytest.mark.asyncio
async def test_get_history_stats(history_db):
    """Stats should compute correct aggregates over completed results."""
    db = history_db["db"]
    user_id = history_db["user_id"]

    stats = await get_history_stats(db, user_id)
    assert stats["total_assessments"] == 5  # Only complete, not grading
    assert stats["average_score"] == 70.0  # (50+60+70+80+90)/5
    assert stats["highest_score"] == 90.0
    assert stats["latest_proficiency_label"] == "expert"


@pytest.mark.asyncio
async def test_get_history_stats_empty_user(db_session: AsyncSession):
    """Stats for a user with no results should return zero defaults."""
    stats = await get_history_stats(db_session, uuid.uuid4())
    assert stats["total_assessments"] == 0
    assert stats["average_score"] == 0.0
    assert stats["highest_score"] == 0.0
    assert stats["latest_proficiency_label"] == "novice"


@pytest.mark.asyncio
async def test_get_trend_data(history_db):
    """Trend should return chronologically ordered data points."""
    db = history_db["db"]
    user_id = history_db["user_id"]

    data = await get_trend_data(db, user_id)
    assert len(data) == 5  # Only complete results

    # Should be ordered by date ascending
    dates = [d["date"] for d in data]
    assert dates == sorted(dates)

    # Scores should match our fixture data
    scores = [d["score"] for d in data]
    assert scores == [50.0, 60.0, 70.0, 80.0, 90.0]


@pytest.mark.asyncio
async def test_get_trend_data_empty(db_session: AsyncSession):
    """Trend for a user with no results should return empty list."""
    data = await get_trend_data(db_session, uuid.uuid4())
    assert data == []
