"""Results API endpoints (SPEC-032/034)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.database import get_db
from src.dependencies import get_current_user
from src.scoring.schemas import (
    CompareResponse,
    CompetencyScoreResponse,
    GradingStatusResponse,
    HistoryResponse,
    HistoryStatsResponse,
    RadarDataPoint,
    RadarResponse,
    ResultResponse,
    ResultSummary,
    TrendResponse,
)
from src.scoring.service import (
    get_competency_scores,
    get_history,
    get_history_stats,
    get_result,
    get_trend_data,
)

router = APIRouter()


# --- History endpoints (must come before /{assessment_id} to avoid path conflicts) ---


@router.get("/history", response_model=HistoryResponse)
async def list_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    status: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Get paginated assessment result history."""
    items, total_count = await get_history(
        db, current_user.id, page, per_page, status, from_date, to_date
    )
    return {
        "items": [ResultSummary.model_validate(item) for item in items],
        "total_count": total_count,
        "page": page,
        "per_page": per_page,
    }


@router.get("/history/stats", response_model=HistoryStatsResponse)
async def history_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Get summary statistics for assessment history."""
    return await get_history_stats(db, current_user.id)


@router.get("/history/trend", response_model=TrendResponse)
async def history_trend(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Get score trend data points for chart visualization."""
    data = await get_trend_data(db, current_user.id)
    return {"data": data}


@router.get("/compare", response_model=CompareResponse)
async def compare_results(
    ids: str = Query(..., description="Comma-separated assessment IDs (exactly 2)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Compare two assessment results side by side."""
    id_list = [s.strip() for s in ids.split(",")]
    if len(id_list) != 2:
        from src.errors import AppError

        raise AppError("Exactly 2 assessment IDs are required for comparison", status_code=400)

    results = []
    for assessment_id_str in id_list:
        assessment_id = uuid.UUID(assessment_id_str)
        result = await get_result(db, assessment_id, current_user.id)
        scores = await get_competency_scores(db, result.id)

        result_dict = ResultResponse.model_validate(result).model_dump()
        result_dict["competency_scores"] = [
            CompetencyScoreResponse(
                competency_id=s.competency_id,
                score=s.score,
                proficiency_level=s.proficiency_level,
                questions_total=s.questions_total,
                questions_correct=s.questions_correct,
                ai_graded_avg=s.ai_graded_avg,
            )
            for s in scores
        ]
        results.append(result_dict)

    return {"results": results}


# --- Single assessment result endpoints ---


@router.get("/{assessment_id}", response_model=ResultResponse)
async def get_results(
    assessment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Get full results for a completed assessment."""
    result = await get_result(db, assessment_id, current_user.id)
    scores = await get_competency_scores(db, result.id)

    return {
        **ResultResponse.model_validate(result).model_dump(),
        "competency_scores": [
            CompetencyScoreResponse(
                competency_id=s.competency_id,
                score=s.score,
                proficiency_level=s.proficiency_level,
                questions_total=s.questions_total,
                questions_correct=s.questions_correct,
                ai_graded_avg=s.ai_graded_avg,
            )
            for s in scores
        ],
    }


@router.get("/{assessment_id}/radar", response_model=RadarResponse)
async def get_radar_data(
    assessment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Get radar chart data for results visualization."""
    result = await get_result(db, assessment_id, current_user.id)
    scores = await get_competency_scores(db, result.id)

    return {
        "data": [
            RadarDataPoint(
                competency=f"competency_{s.competency_id}",
                score=s.score,
            )
            for s in scores
        ],
    }


@router.get("/{assessment_id}/grading-status", response_model=GradingStatusResponse)
async def grading_status(
    assessment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Check AI grading progress."""
    result = await get_result(db, assessment_id, current_user.id)

    return {
        "assessment_id": assessment_id,
        "grading_status": result.grading_status,
        "total_to_grade": 0,
        "graded_count": 0,
        "progress_percent": 0.0 if result.grading_status == "pending" else 100.0,
    }
