"""Question-related API endpoints (SPEC-013)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.questions.models import Competency
from src.questions.schemas import CompetencyResponse

router = APIRouter()


@router.get("/competencies", response_model=list[CompetencyResponse])
async def list_competencies(
    db: AsyncSession = Depends(get_db),
) -> list[Competency]:
    """List all competency groups."""
    result = await db.execute(select(Competency).order_by(Competency.id))
    return list(result.scalars().all())
