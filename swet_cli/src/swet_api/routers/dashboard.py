"""Dashboard API router: aggregated Today page data."""

from typing import Annotated

from fastapi import APIRouter, Depends

from swet_api.auth.dependencies import get_current_user
from swet_api.db import get_dashboard_data
from swet_api.schemas import DashboardResponse, StreakResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    user: Annotated[dict, Depends(get_current_user)],
) -> DashboardResponse:
    """Get aggregated data for the Today page."""
    data = get_dashboard_data(user["id"])
    return DashboardResponse(
        streak=StreakResponse(**data["streak"]),
        review_due_count=data["review_due_count"],
        has_completed_assessment=data["has_completed_assessment"],
        focus_competency=data["focus_competency"],
        total_attempts=data["total_attempts"],
        competencies_assessed=data["competencies_assessed"],
    )
