"""Stats API router."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from swet_api.auth.dependencies import get_current_user
from swet_api.db import (
    get_format_performance_stats,
    get_streak_calendar,
    get_user_competency_levels,
    get_user_state,
    get_user_stats,
    get_weak_areas,
)
from swet_api.schemas import (
    CompetencyLevelResponse,
    FormatPerformanceResponse,
    StatsResponse,
    StreakCalendarResponse,
    StreakResponse,
    WeakAreaResponse,
)

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=list[StatsResponse])
def stats(user: Annotated[dict, Depends(get_current_user)]) -> list[StatsResponse]:
    """Get aggregate stats by competency."""
    data = get_user_stats(user["id"])
    return [StatsResponse(**row) for row in data]


@router.get("/streak", response_model=StreakResponse)
def streak(user: Annotated[dict, Depends(get_current_user)]) -> StreakResponse:
    """Get current and longest streak."""
    current = get_user_state(user["id"], "current_streak")
    longest = get_user_state(user["id"], "longest_streak")
    return StreakResponse(
        current_streak=int(current) if current else 0,
        longest_streak=int(longest) if longest else 0,
    )


@router.get("/competencies", response_model=list[CompetencyLevelResponse])
def competency_levels(user: Annotated[dict, Depends(get_current_user)]) -> list[CompetencyLevelResponse]:
    """Get all competencies with their estimated levels."""
    from swet_cli.data import COMPETENCY_BY_SLUG, COMPETENCY_SLUGS

    levels = get_user_competency_levels(user["id"])
    results: list[CompetencyLevelResponse] = []

    for slug in COMPETENCY_SLUGS:
        comp = COMPETENCY_BY_SLUG[slug]
        level_data = levels.get(slug)
        results.append(
            CompetencyLevelResponse(
                slug=slug,
                name=comp.name,
                estimated_level=level_data["estimated_level"] if level_data else None,
                total_attempts=level_data["total_attempts"] if level_data else 0,
            )
        )

    return results


@router.get("/calendar", response_model=StreakCalendarResponse)
def calendar(
    user: Annotated[dict, Depends(get_current_user)],
    year: int | None = None,
    month: int | None = None,
) -> StreakCalendarResponse:
    """Get contribution-style calendar data for a month."""
    today = date.today()
    y = year or today.year
    m = month or today.month
    active_days = get_streak_calendar(user["id"], y, m)
    return StreakCalendarResponse(year=y, month=m, active_days=active_days)


@router.get("/format-performance", response_model=list[FormatPerformanceResponse])
def format_performance(
    user: Annotated[dict, Depends(get_current_user)],
) -> list[FormatPerformanceResponse]:
    """Get performance breakdown by question format."""
    data = get_format_performance_stats(user["id"])
    return [FormatPerformanceResponse(**row) for row in data]


@router.get("/weak-areas", response_model=list[WeakAreaResponse])
def weak_areas(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 5,
) -> list[WeakAreaResponse]:
    """Get the weakest competencies by average score."""
    data = get_weak_areas(user["id"], limit=limit)
    return [WeakAreaResponse(**row) for row in data]
